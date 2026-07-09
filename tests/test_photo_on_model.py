"""G6 — a closet/deck card must NEVER show a person.

An ON-MODEL photo cutout (from a source photo with a person) contains a person. It is kept
only as the generation/self-heal REFERENCE (image_url); NO display path — the review deck
view, the closet read, or the confirm write — may ever surface it. It shows only once a
verified, person-free generated card lands. A flat-lay crop (on_model=false) still shows.
"""
import uuid

from app.api.routes.closet import _get_image_url
from app.gmail_closet.review_service import _candidate_to_view
from app.models import ClothingItem, IngestCandidate


def _cand(**over) -> IngestCandidate:
    base = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name="Camel Coat",
        brand=None,
        category="outerwear",
        color="camel",
        size=None,
        quantity=1,
        is_return=False,
        image_url="https://cdn/crop-with-person.jpg",
        image_status="user_uploaded",
        source_type="photo",
        on_model=True,
        generated_image_url=None,
        generation_status="pending_retry",
        confidence_overall=0.8,
        confidence_json={},
        seen_count=1,
        status="pending",
    )
    base.update(over)
    return IngestCandidate(**base)


# --------------------------------------------------------------------------- deck view
def test_candidate_view_masks_on_model_crop_pending_retry():
    view = _candidate_to_view(_cand(), None)
    assert view["on_model"] is True
    assert view["image_url"] is None          # the person crop is NEVER sent
    assert view["generated_image_url"] is None


def test_candidate_view_masks_on_model_crop_even_when_ready():
    # Even 'ready': the CANDIDATE's image_url is always the raw crop (the card lives in
    # generated_image_url), so it must stay masked. The deck shows the generated card.
    view = _candidate_to_view(
        _cand(generation_status="ready", generated_image_url="https://cdn/clean-card.jpg"), None
    )
    assert view["image_url"] is None
    assert view["generated_image_url"] == "https://cdn/clean-card.jpg"


def test_candidate_view_masks_on_model_while_generating():
    view = _candidate_to_view(_cand(generation_status="generating"), None)
    assert view["image_url"] is None


def test_candidate_view_shows_flatlay_crop():
    # A flat-lay photo (no person) is safe to show as before.
    view = _candidate_to_view(_cand(on_model=False, generation_status="pending_retry"), None)
    assert view["image_url"] == "https://cdn/crop-with-person.jpg"  # here: a clean flat-lay crop
    assert view["on_model"] is False


# --------------------------------------------------------------------------- closet read
def _item(**over) -> ClothingItem:
    base = dict(
        id=uuid.uuid4(), user_id=uuid.uuid4(), name="Camel Coat", category="outerwear",
        source_type="photo", on_model=True, generation_status="pending_retry",
        image_url="https://cdn/crop-with-person.jpg",
    )
    base.update(over)
    return ClothingItem(**base)


def test_closet_read_masks_on_model_until_ready():
    assert _get_image_url(_item(generation_status="pending_retry")) is None
    assert _get_image_url(_item(generation_status="generating")) is None
    assert _get_image_url(_item(generation_status=None)) is None


def test_closet_read_shows_generated_card_when_ready():
    # When ready, image_url IS the verified person-free generated card (generation replaced
    # the crop in place) — so it is safe to show.
    it = _item(generation_status="ready", image_url="https://cdn/clean-card.jpg")
    assert _get_image_url(it) == "https://cdn/clean-card.jpg"


def test_closet_read_shows_flatlay_crop():
    it = _item(on_model=False, generation_status="pending_retry", image_url="https://cdn/flatlay.jpg")
    assert _get_image_url(it) == "https://cdn/flatlay.jpg"


# --------------------------------------------------------------------------- stage flag
def test_stage_sets_on_model_from_person_count():
    """A cutout from an on-model photo (person_count>=1) is flagged; a flat-lay is not.

    (confirm_candidates itself uses a Postgres-only ON CONFLICT ... (xmax=0) upsert, so the
    end-to-end confirm write is exercised in the Postgres-backed suite; here we cover the
    stage flag + the display masks, which are the actual no-person guarantee.)"""
    from types import SimpleNamespace

    from app.photo_closet.detection import GarmentCategory
    from app.photo_closet.ingest_service import _stage_candidate

    class _FakeDB:
        def query(self, *a, **k):
            return self

        def filter(self, *a, **k):
            return self

        def first(self):
            return None  # no existing row -> insert path

        def add(self, *a, **k):
            pass

    garment = SimpleNamespace(
        name="Camel Coat", brand=None, category=GarmentCategory.outerwear, color="camel",
        confidence_overall=0.8,
        confidence=SimpleNamespace(name=0.8, brand=None, category=0.8, color=0.7),
    )
    on = _stage_candidate(_FakeDB(), uuid.uuid4(), uuid.uuid4(), garment, "u", "slk", on_model=True)
    off = _stage_candidate(_FakeDB(), uuid.uuid4(), uuid.uuid4(), garment, "u", "slk", on_model=False)
    assert on.on_model is True
    assert off.on_model is False


# --------------------------------------------------------------------------- C1: every display surface masks
def test_shared_display_mask_helper():
    from app.models.closet import display_image_url

    assert display_image_url(_item(on_model=True, generation_status="pending_retry")) is None
    assert display_image_url(_item(on_model=True, generation_status=None)) is None
    assert display_image_url(_item(on_model=True, generation_status="ready", image_url="card")) == "card"
    assert display_image_url(_item(on_model=False, generation_status="pending_retry", image_url="flat")) == "flat"


def test_collage_usable_image_url_masks_on_model():
    from app.services.stylist.collage import usable_image_url

    # on-model, not ready -> excluded from any collage (never composited)
    assert usable_image_url(_item(on_model=True, generation_status="pending_retry", image_status="user_uploaded")) is None
    # on-model, ready -> image_url IS the verified card -> usable
    assert usable_image_url(_item(on_model=True, generation_status="ready", image_url="card", image_status="user_uploaded")) == "card"
    # flat-lay ready -> usable
    assert usable_image_url(_item(on_model=False, generation_status="ready", image_url="flat", image_status="user_uploaded")) == "flat"


def test_retrieval_serialize_item_masks_on_model():
    from app.services.stylist.retrieval import serialize_item

    masked = serialize_item(_item(on_model=True, generation_status="pending_retry", image_url="crop-person"))
    assert masked["imageUrl"] is None
    shown = serialize_item(_item(on_model=True, generation_status="ready", image_url="clean-card"))
    assert shown["imageUrl"] == "clean-card"
    flat = serialize_item(_item(on_model=False, generation_status="pending_retry", image_url="flatlay"))
    assert flat["imageUrl"] == "flatlay"


# --------------------------------------------------------------------------- C2: confirm never stores a 'ready' crop
def test_item_generation_status_never_ready_with_a_crop_for_on_model():
    from types import SimpleNamespace

    from app.gmail_closet.review_service import _item_generation_status

    def cand(**kw):
        base = dict(on_model=True, generation_status="ready", generated_image_url=None)
        base.update(kw)
        return SimpleNamespace(**base)

    # on-model 'ready' but NO verified card -> forced pending_retry (stays masked)
    assert _item_generation_status(cand()) == "pending_retry"
    # on-model 'ready' WITH a verified card -> ready (the card, not a crop, is shown)
    assert _item_generation_status(cand(generated_image_url="card")) == "ready"
    # on-model pending_retry -> pending_retry
    assert _item_generation_status(cand(generation_status="pending_retry")) == "pending_retry"
    # NON-on-model keeps the candidate's status verbatim (unchanged behavior)
    assert _item_generation_status(cand(on_model=False)) == "ready"
    assert _item_generation_status(cand(on_model=False, generation_status="pending_retry")) == "pending_retry"
