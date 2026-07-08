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


def test_regeneration_skips_non_photo_and_foreign(db, user, monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(gs, "_generate_from_crop",
                        lambda **k: called.__setitem__("n", called["n"] + 1) or gs._HealOutcome("ready", url="u"))
    gmail_item = _photo_item(db, user, source_type="gmail", generation_status=None)
    assert gs.run_item_regeneration(user.id, db, gmail_item.id).status == "skipped"
    assert gs.run_item_regeneration(user.id, db, uuid.uuid4()).status == "skipped"
    assert called["n"] == 0  # never reached the generator


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
    assert client.post(f"/closet/{uuid.uuid4()}/regenerate", json={}).status_code == 401


def test_regenerate_cross_user_is_404(client, db, user, other_user):
    item = _photo_item(db, user)
    tok = mint_supabase_token(sub=str(other_user.id))
    r = client.post(f"/closet/{item.id}/regenerate", json={},
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 404


def test_regenerate_non_photo_is_400(client, db, user):
    item = _photo_item(db, user, source_type="gmail", generation_status=None)
    tok = mint_supabase_token(sub=str(user.id))
    r = client.post(f"/closet/{item.id}/regenerate", json={"reason": "x"},
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 400


def test_regenerate_photo_marks_generating_and_records_quota(client, db, user, monkeypatch):
    monkeypatch.setattr(settings, "JOBS_PHOTO_GENERATION_ENABLED", False)
    scheduled = []
    monkeypatch.setattr(
        gs, "regenerate_item_background",
        lambda uid, iid, reason=None: scheduled.append((uid, iid, reason)),
    )
    item = _photo_item(db, user, generation_status="ready")
    tok = mint_supabase_token(sub=str(user.id))

    r = client.post(
        f"/closet/{item.id}/regenerate",
        json={"reason": "the swoosh should be red, not black"},
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
