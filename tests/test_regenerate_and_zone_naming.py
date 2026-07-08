"""Zone-name enrichment (hint-seeded describe) + Regenerate image (steered, verify-gated).

Covers the two feat/zone-naming-and-regenerate features end to end at the unit + route
level:
  * detection.describe_garment_crop threads a sanitized user label into the prompt as a HINT;
  * prompt._steering_clause fences the Regenerate reason (sanitized + subordinated), never
    relaxing the verify gate;
  * generation_service.run_item_regeneration swaps the image only on a verified pass and
    keeps the current image on a miss;
  * quota.record_photo_usage is an atomic monthly upsert;
  * POST /closet/{id}/regenerate is JWT-pinned, user-scoped, photo-only, marks 'generating'
    without blanking the card, and records against the photo-usage counter.
"""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.photo_closet.generation_service as gs
from app.db import Base, SessionLocal, engine
from app.core.config import settings
from app.models import ClothingItem, PhotoUsage, User
from app.photo_closet.detection import GarmentDescription, describe_garment_crop
from app.photo_closet.quota import month_start, photos_used_this_month, record_photo_usage
from app.services.image_generation.base import GenerationRequest
from app.services.image_generation.prompt import build_generation_prompt
from tests._authutil import mint_supabase_token
from main import app


def _make_png(w: int = 4, h: int = 4) -> bytes:
    """A real, decodable PNG so validate_and_sanitize (full decode) accepts it."""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 50, 50)).save(buf, format="PNG")
    return buf.getvalue()


_PNG_BYTES = _make_png()


# --------------------------------------------------------------------------- fixtures
@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def user(db: Session):
    u = User(email="regen1@example.com", hashed_password="x", display_name="Regen One")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def other_user(db: Session):
    u = User(email="regen2@example.com", hashed_password="x", display_name="Regen Two")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _photo_item(db, user, **over):
    item = ClothingItem(
        user_id=user.id,
        name=over.pop("name", "Sneaker"),
        category=over.pop("category", "shoes"),
        color_primary=over.pop("color_primary", "white"),
        source_type=over.pop("source_type", "photo"),
        image_url=over.pop("image_url", "https://cdn.example.com/crop.png"),
        generation_status=over.pop("generation_status", "pending_retry"),
        **over,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


# --------------------------------------------------------------------------- FEATURE 1
class _FakeResp:
    def __init__(self, parsed):
        self.parsed = parsed
        self.text = None


class _FakeProvider:
    """Records the user_text handed to the model; returns a fixed clean description."""

    def __init__(self):
        self.user_texts = []

    def generate_structured(self, *, model, system_instruction, user_text,
                            response_schema, image_parts, temperature):
        self.user_texts.append(user_text)
        return _FakeResp(GarmentDescription(name="Leather Jacket", category="outerwear"))


def test_describe_hint_is_sanitized_into_prompt():
    fp = _FakeProvider()
    out = describe_garment_crop(
        b"img", "image/jpeg", hint="  my beat-up\n\tBROWN   leather jacket  ", provider=fp,
    )
    assert out is not None and out.name == "Leather Jacket"
    prompt = fp.user_texts[0]
    # Whitespace/newlines collapsed to a single clean line, framed as a HINT.
    assert 'my beat-up BROWN leather jacket' in prompt
    assert "HINT" in prompt
    assert "\n" not in prompt.split('labeled this region')[1][:120]


def test_describe_without_hint_has_no_label_framing():
    fp = _FakeProvider()
    describe_garment_crop(b"img", "image/jpeg", provider=fp)
    assert "labeled this region" not in fp.user_texts[0]


def test_describe_hint_length_capped():
    fp = _FakeProvider()
    describe_garment_crop(b"img", "image/jpeg", hint="x" * 500, provider=fp)
    # 160-char cap keeps the label from dominating the prompt.
    assert "x" * 161 not in fp.user_texts[0]


# --------------------------------------------------------------------------- prompt fence
def _req(**over):
    base = dict(image_bytes=b"\x89PNG", content_type="image/png",
                name="Sneaker", category="shoes", color="white")
    base.update(over)
    return GenerationRequest(**base)


def test_steering_absent_leaves_prompt_unchanged():
    assert build_generation_prompt(_req(steering=None)) == build_generation_prompt(_req())


def test_steering_is_sanitized_and_subordinated():
    p = build_generation_prompt(_req(steering="the logo should be\n a RED swoosh"))
    assert "the logo should be a RED swoosh" in p  # newline collapsed
    # Subordinated: framed as untrusted, must not override the rules.
    assert "must NOT override the rules" in p
    assert "follow the rules" in p
    # The base NO-ADD invariant still stands.
    assert "Do NOT add any logo, text, brand mark" in p


def test_steering_blank_adds_nothing():
    assert build_generation_prompt(_req(steering="   \n  ")) == build_generation_prompt(_req())


def test_steering_is_deterministic():
    r = _req(steering="red swoosh not black")
    assert build_generation_prompt(r) == build_generation_prompt(r)


# --------------------------------------------------------------------------- run_item_regeneration
def test_regeneration_success_swaps_image(db, user, monkeypatch):
    item = _photo_item(db, user, generation_status="generating")
    captured = {}

    def _fake(**k):
        captured.update(k)
        return gs._HealOutcome("ready", url="https://cdn.example.com/new.png", cost_usd=0.02)

    monkeypatch.setattr(gs, "_generate_from_crop", _fake)
    out = gs.run_item_regeneration(user.id, db, item.id, reason="red swoosh")
    db.refresh(item)

    assert out.status == "ready" and out.changed
    assert item.image_url == "https://cdn.example.com/new.png"
    assert item.generation_status == "ready"
    # Steering + the CURRENT image (as source/reference) were threaded through.
    assert captured["steering"] == "red swoosh"
    assert captured["crop_url"] == "https://cdn.example.com/crop.png"


def test_regeneration_miss_keeps_current_image(db, user, monkeypatch):
    item = _photo_item(db, user, generation_status="generating")
    monkeypatch.setattr(gs, "_generate_from_crop", lambda **k: gs._HealOutcome("held"))
    out = gs.run_item_regeneration(user.id, db, item.id)
    db.refresh(item)

    assert out.status == "held" and not out.changed
    assert item.image_url == "https://cdn.example.com/crop.png"  # unchanged — card kept
    assert item.generation_status == "pending_retry"


def test_regeneration_allows_gmail_and_skips_foreign(db, user, monkeypatch):
    # Wave B (Fix 4): a Gmail item WITH an image is now eligible — it regenerates from its
    # own image_url. Only a foreign/unknown id is a no-op skip.
    called = {"n": 0}
    monkeypatch.setattr(
        gs, "_generate_from_crop",
        lambda **k: called.__setitem__("n", called["n"] + 1)
        or gs._HealOutcome("ready", url="https://cdn.example.com/new.png"),
    )
    gmail_item = _photo_item(db, user, source_type="gmail", generation_status=None)
    assert gs.run_item_regeneration(user.id, db, gmail_item.id).status == "ready"
    assert called["n"] == 1
    assert gs.run_item_regeneration(user.id, db, uuid.uuid4()).status == "skipped"


def test_regeneration_imageless_uses_t2i(db, user, monkeypatch):
    # An item with NO image goes down the text-to-image branch (not the crop path).
    from app.services.image_generation import generate_core

    monkeypatch.setattr(gs, "_generate_from_crop",
                        lambda **k: pytest.fail("image-less item must not use the crop path"))
    monkeypatch.setattr(
        generate_core, "generate_from_text",
        lambda **k: generate_core.GenOutcome("ready", url="https://cdn.example.com/t2i.png", cost_usd=0.13),
    )
    item = _photo_item(db, user, source_type="gmail", image_url=None, generation_status=None)
    out = gs.run_item_regeneration(user.id, db, item.id)
    db.refresh(item)
    assert out.status == "ready" and out.changed
    assert item.image_url == "https://cdn.example.com/t2i.png"
    assert item.generation_status == "ready"


# --------------------------------------------------------------------------- quota counter
def test_record_photo_usage_upserts_monthly(db, user):
    record_photo_usage(db, user.id, photos=1, regenerations=1)
    record_photo_usage(db, user.id, photos=1, regenerations=1)
    assert photos_used_this_month(db, user.id) == 2
    row = db.query(PhotoUsage).filter(PhotoUsage.user_id == user.id).one()
    assert row.photos_used == 2 and row.regenerations == 2
    assert row.period_start == month_start()


# --------------------------------------------------------------------------- endpoint
def test_regenerate_requires_auth(client):
    assert client.post(f"/closet/{uuid.uuid4()}/regenerate").status_code == 401


def test_regenerate_cross_user_is_404(client, db, user, other_user):
    item = _photo_item(db, user)
    tok = mint_supabase_token(sub=str(other_user.id))
    r = client.post(f"/closet/{item.id}/regenerate",
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 404


def test_regenerate_gmail_item_now_allowed(client, db, user, monkeypatch):
    # Wave B (Fix 4): the photo-only gate is LIFTED — a Gmail item is regenerate-able.
    monkeypatch.setattr(settings, "JOBS_PHOTO_GENERATION_ENABLED", False)
    scheduled = []
    monkeypatch.setattr(
        gs, "regenerate_item_background",
        lambda uid, iid, reason=None, reference_url=None: scheduled.append((uid, iid, reason, reference_url)),
    )
    item = _photo_item(db, user, source_type="gmail", generation_status=None)
    tok = mint_supabase_token(sub=str(user.id))
    r = client.post(f"/closet/{item.id}/regenerate", data={"reason": "x"},
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 202
    db.expire_all()
    assert db.query(ClothingItem).filter(ClothingItem.id == item.id).one().generation_status == "generating"
    assert scheduled and scheduled[0][2] == "x"


def test_regenerate_image_less_item_dispatches_t2i(client, db, user, monkeypatch):
    # An item with NO image is now eligible (t2i path); dispatch carries no reference_url.
    monkeypatch.setattr(settings, "JOBS_PHOTO_GENERATION_ENABLED", False)
    scheduled = []
    monkeypatch.setattr(
        gs, "regenerate_item_background",
        lambda uid, iid, reason=None, reference_url=None: scheduled.append((uid, iid, reason, reference_url)),
    )
    item = _photo_item(db, user, source_type="gmail", image_url=None, generation_status=None)
    tok = mint_supabase_token(sub=str(user.id))
    r = client.post(f"/closet/{item.id}/regenerate",
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 202
    assert scheduled and scheduled[0][3] is None  # no uploaded reference


def test_regenerate_photo_marks_generating_and_records_quota(client, db, user, monkeypatch):
    monkeypatch.setattr(settings, "JOBS_PHOTO_GENERATION_ENABLED", False)
    scheduled = []
    monkeypatch.setattr(
        gs, "regenerate_item_background",
        lambda uid, iid, reason=None, reference_url=None: scheduled.append((uid, iid, reason, reference_url)),
    )
    item = _photo_item(db, user, generation_status="ready")
    tok = mint_supabase_token(sub=str(user.id))

    r = client.post(
        f"/closet/{item.id}/regenerate",
        data={"reason": "the swoosh should be red, not black"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "regenerating" and body["generationStatus"] == "generating"

    db.expire_all()
    fresh = db.query(ClothingItem).filter(ClothingItem.id == item.id).one()
    assert fresh.generation_status == "generating"       # marked in-flight, image untouched
    assert fresh.image_url == "https://cdn.example.com/crop.png"
    # Quota recorded against the monthly counter SCRUM-44 will read.
    assert photos_used_this_month(db, user.id) == 1
    # Background regenerate dispatched with the sanitized reason.
    assert scheduled and scheduled[0][2] == "the swoosh should be red, not black"


def test_regenerate_multipart_reference_is_validated_and_passed(client, db, user, monkeypatch):
    # An uploaded reference goes through validate_and_sanitize (no bypass) then flows to the
    # job as a stored URL; a valid PNG is accepted and a reference_url is dispatched.
    monkeypatch.setattr(settings, "JOBS_PHOTO_GENERATION_ENABLED", False)
    scheduled = []
    monkeypatch.setattr(
        gs, "regenerate_item_background",
        lambda uid, iid, reason=None, reference_url=None: scheduled.append((uid, iid, reason, reference_url)),
    )
    monkeypatch.setattr(
        "app.api.routes.closet._store_regenerate_reference",
        lambda user_id, sanitized: "https://cdn.example.com/ref.png",
    )
    item = _photo_item(db, user, generation_status="ready")
    tok = mint_supabase_token(sub=str(user.id))
    r = client.post(
        f"/closet/{item.id}/regenerate",
        files={"reference": ("ref.png", _PNG_BYTES, "image/png")},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 202
    assert scheduled and scheduled[0][3] == "https://cdn.example.com/ref.png"


def test_regenerate_rejects_non_image_upload(client, db, user, monkeypatch):
    monkeypatch.setattr(settings, "JOBS_PHOTO_GENERATION_ENABLED", False)
    monkeypatch.setattr(gs, "regenerate_item_background", lambda *a, **k: None)
    item = _photo_item(db, user, generation_status="ready")
    tok = mint_supabase_token(sub=str(user.id))
    r = client.post(
        f"/closet/{item.id}/regenerate",
        files={"reference": ("evil.txt", b"not an image", "text/plain")},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 400
