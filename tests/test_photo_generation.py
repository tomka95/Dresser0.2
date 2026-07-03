"""Wave 2 background product-image generation for photo candidates.

SQLite DB; the provider seam, the verify gate, cutout download and blob storage are all
faked so these tests exercise ONLY the orchestration: the nano->flux ladder, the
mandatory fidelity gate, per-candidate lifecycle writes, run counters + deferred
finalization, budget cap, and idempotency."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine
from app.models import ClothingItem, IngestCandidate, IngestRun, User
from app.gmail_closet.image_verify import VerifyVerdict
from app.photo_closet import generation_service as gen
from app.services.image_generation.base import GenerationResult


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
def user(db: Session):
    u = User(email="g@example.com", hashed_password="x", display_name="G")
    db.add(u); db.commit(); db.refresh(u)
    return u


# --- fakes -------------------------------------------------------------------

class _FakeProvider:
    def __init__(self, name, result):
        self.name = name
        self._result = result
        self.calls = 0

    def generate(self, req):
        self.calls += 1
        return self._result


def _result(provider: str, cost: float = 0.134) -> GenerationResult:
    # Distinct bytes per provider so a verify fake can pass one rung and fail another.
    return GenerationResult(
        image_bytes=b"gen-" + provider.encode(),
        content_type="image/png",
        provider=provider,
        model="m",
        latency_s=0.1,
        cost_usd=cost,
    )


def _ok() -> VerifyVerdict:
    return VerifyVerdict(True, True, True, 0.9, "ok", "m")


def _fail() -> VerifyVerdict:
    return VerifyVerdict(False, False, True, 0.1, "wrong garment", "m")


def _skipped() -> VerifyVerdict:
    return VerifyVerdict(False, False, False, 0.0, "verify disabled", "m", skipped=True)


def _providers(monkeypatch, mapping):
    monkeypatch.setattr(gen, "get_generation_provider", lambda name=None: mapping[name])
    return mapping


def _verify(monkeypatch, fn):
    monkeypatch.setattr(gen, "verify_generated_image", fn)


def _seams(monkeypatch, download=(b"cut", "image/jpeg"), store="https://blob/gen.png"):
    """Fake cutout download + blob store; return a call-count dict for the store."""
    monkeypatch.setattr(gen, "_download_bytes", lambda url: download)
    calls = {"store": 0}

    def _store(sc, uid, data, ct):
        calls["store"] += 1
        return store

    monkeypatch.setattr(gen, "_store_generated", _store)
    return calls


def _stage(db, user, sync_id, **over):
    fields = dict(
        user_id=user.id, sync_id=sync_id, source_type="photo", status="pending",
        image_url="https://blob/cut.jpg", image_status="user_uploaded",
        name="Tee", category="top", color="red", generation_status=None,
    )
    fields.update(over)
    c = IngestCandidate(**fields)
    db.add(c); db.commit(); db.refresh(c)
    return c


def _run_row(db, user, sync_id):
    r = IngestRun(sync_id=sync_id, user_id=user.id, status="running", source_type="photo")
    db.add(r); db.commit()
    return r


def _run(db, sync_id) -> IngestRun:
    return db.query(IngestRun).filter(IngestRun.sync_id == sync_id).one()


# --- the ladder --------------------------------------------------------------

def test_nano_pass_stores_ready(db, user, monkeypatch):
    _seams(monkeypatch)
    sync = uuid4(); _run_row(db, user, sync); c = _stage(db, user, sync)
    nano = _FakeProvider("nano_banana", _result("nano_banana"))
    flux = _FakeProvider("flux_kontext", _result("flux_kontext"))
    _providers(monkeypatch, {"nano_banana": nano, "flux_kontext": flux})
    _verify(monkeypatch, lambda **k: _ok())

    stats = gen.run_photo_generation(user.id, db, sync)

    db.refresh(c)
    assert c.generation_status == "ready"
    assert c.generated_image_url == "https://blob/gen.png"
    assert c.image_url == "https://blob/cut.jpg"       # crop never overwritten
    assert c.image_status == "user_uploaded"           # image_status untouched
    assert nano.calls == 1 and flux.calls == 0         # nano passed -> no fallback
    run = _run(db, sync)
    assert run.status == "completed" and run.finished_at is not None
    assert (run.generation_total, run.generation_ready, run.generation_failed) == (1, 1, 0)
    assert stats.ready == 1 and stats.held == 0
    assert stats.cost_usd == pytest.approx(0.134)


def test_flux_fallback_on_verify_fail(db, user, monkeypatch):
    _seams(monkeypatch)
    sync = uuid4(); _run_row(db, user, sync); c = _stage(db, user, sync)
    nano = _FakeProvider("nano_banana", _result("nano_banana"))
    flux = _FakeProvider("flux_kontext", _result("flux_kontext"))
    _providers(monkeypatch, {"nano_banana": nano, "flux_kontext": flux})
    # Only the flux candidate passes the gate; nano's is rejected -> retry.
    _verify(monkeypatch, lambda **k: _ok() if k["candidate_bytes"] == b"gen-flux_kontext" else _fail())

    gen.run_photo_generation(user.id, db, sync)

    db.refresh(c)
    assert c.generation_status == "ready"
    assert nano.calls == 1 and flux.calls == 1         # ladder walked to flux
    run = _run(db, sync)
    assert run.generation_ready == 1 and run.generation_failed == 0


def test_both_fail_holds_for_retry(db, user, monkeypatch):
    _seams(monkeypatch)
    sync = uuid4(); _run_row(db, user, sync); c = _stage(db, user, sync)
    _providers(monkeypatch, {
        "nano_banana": _FakeProvider("nano_banana", _result("nano_banana")),
        "flux_kontext": _FakeProvider("flux_kontext", _result("flux_kontext")),
    })
    _verify(monkeypatch, lambda **k: _fail())

    stats = gen.run_photo_generation(user.id, db, sync)

    db.refresh(c)
    assert c.generation_status == "pending_retry"
    assert c.generated_image_url is None               # nothing stored
    assert c.image_url == "https://blob/cut.jpg"        # crop untouched (no raw fallback)
    run = _run(db, sync)
    assert run.status == "completed"
    assert (run.generation_ready, run.generation_failed) == (0, 1)
    assert stats.held == 1 and stats.ready == 0


def test_provider_unavailable_holds_without_verify(db, user, monkeypatch):
    store = _seams(monkeypatch)
    sync = uuid4(); _run_row(db, user, sync); c = _stage(db, user, sync)
    # Both providers unavailable (Null / balance): generate() returns None.
    _providers(monkeypatch, {
        "nano_banana": _FakeProvider("nano_banana", None),
        "flux_kontext": _FakeProvider("flux_kontext", None),
    })
    verify_calls = []
    _verify(monkeypatch, lambda **k: verify_calls.append(1) or _ok())

    gen.run_photo_generation(user.id, db, sync)

    db.refresh(c)
    assert c.generation_status == "pending_retry"
    assert verify_calls == []          # never verify when no image was produced
    assert store["store"] == 0         # nothing stored


def test_verify_skipped_is_not_stored(db, user, monkeypatch):
    """The fidelity gate is mandatory: a skipped/disabled verify must NOT store."""
    store = _seams(monkeypatch)
    sync = uuid4(); _run_row(db, user, sync); c = _stage(db, user, sync)
    _providers(monkeypatch, {
        "nano_banana": _FakeProvider("nano_banana", _result("nano_banana")),
        "flux_kontext": _FakeProvider("flux_kontext", _result("flux_kontext")),
    })
    _verify(monkeypatch, lambda **k: _skipped())

    gen.run_photo_generation(user.id, db, sync)

    db.refresh(c)
    assert c.generation_status == "pending_retry"
    assert c.generated_image_url is None
    assert store["store"] == 0


def test_download_error_holds_before_generate(db, user, monkeypatch):
    _seams(monkeypatch, download=None)  # cutout re-fetch fails
    sync = uuid4(); _run_row(db, user, sync); c = _stage(db, user, sync)
    nano = _FakeProvider("nano_banana", _result("nano_banana"))
    _providers(monkeypatch, {"nano_banana": nano, "flux_kontext": _FakeProvider("flux_kontext", None)})
    _verify(monkeypatch, lambda **k: _ok())

    stats = gen.run_photo_generation(user.id, db, sync)

    db.refresh(c)
    assert c.generation_status == "pending_retry"
    assert nano.calls == 0                     # never generate without a reference
    assert stats.download_errors == 1
    assert _run(db, sync).status == "completed"


def test_idempotent_rerun_skips_ready(db, user, monkeypatch):
    _seams(monkeypatch)
    sync = uuid4(); _run_row(db, user, sync); c = _stage(db, user, sync)
    _providers(monkeypatch, {
        "nano_banana": _FakeProvider("nano_banana", _result("nano_banana")),
        "flux_kontext": _FakeProvider("flux_kontext", _result("flux_kontext")),
    })
    _verify(monkeypatch, lambda **k: _ok())
    gen.run_photo_generation(user.id, db, sync)
    db.refresh(c)
    assert c.generation_status == "ready"

    # Second pass: 'ready' is excluded from the target set -> no provider call.
    nano2 = _FakeProvider("nano_banana", _result("nano_banana"))
    flux2 = _FakeProvider("flux_kontext", _result("flux_kontext"))
    _providers(monkeypatch, {"nano_banana": nano2, "flux_kontext": flux2})
    stats = gen.run_photo_generation(user.id, db, sync)

    assert stats.targets == 0
    assert nano2.calls == 0 and flux2.calls == 0
    db.refresh(c)
    assert c.generated_image_url == "https://blob/gen.png"   # unchanged


def test_budget_cap_leaves_residue(db, user, monkeypatch):
    _seams(monkeypatch)
    monkeypatch.setattr(gen.settings, "GENERATION_MAX_PER_RUN", 0)  # no budget
    sync = uuid4(); _run_row(db, user, sync); c = _stage(db, user, sync)
    nano = _FakeProvider("nano_banana", _result("nano_banana"))
    _providers(monkeypatch, {"nano_banana": nano, "flux_kontext": _FakeProvider("flux_kontext", None)})
    _verify(monkeypatch, lambda **k: _ok())

    stats = gen.run_photo_generation(user.id, db, sync)

    db.refresh(c)
    assert stats.budget_stopped is True
    assert nano.calls == 0
    assert c.generation_status is None          # untouched -> a later sweep retries it
    run = _run(db, sync)
    assert run.status == "completed" and run.generation_total == 1 and run.generation_ready == 0


# --- concurrency -------------------------------------------------------------

def test_concurrent_all_ready_counts_are_race_safe(db, user, monkeypatch):
    """4 candidates generate CONCURRENTLY; every one lands 'ready' and the atomic
    generation_ready counter is exactly 4 (no lost increments across workers)."""
    _seams(monkeypatch)
    sync = uuid4(); _run_row(db, user, sync)
    cands = [_stage(db, user, sync, source_line_key=f"slk{i}", name=f"Item{i}") for i in range(4)]
    nano = _FakeProvider("nano_banana", _result("nano_banana"))
    flux = _FakeProvider("flux_kontext", _result("flux_kontext"))
    _providers(monkeypatch, {"nano_banana": nano, "flux_kontext": flux})
    _verify(monkeypatch, lambda **k: _ok())

    stats = gen.run_photo_generation(user.id, db, sync)

    assert stats.ready == 4 and stats.held == 0
    for c in cands:
        db.refresh(c)
        assert c.generation_status == "ready"
        assert c.generated_image_url == "https://blob/gen.png"
        assert c.image_url == "https://blob/cut.jpg"   # crop never overwritten
    assert flux.calls == 0                              # nano passed every one
    run = _run(db, sync)
    assert run.status == "completed"
    assert (run.generation_total, run.generation_ready, run.generation_failed) == (4, 4, 0)


def test_concurrent_budget_is_shared_across_workers(db, user, monkeypatch):
    """A budget of 2 caps the CONCURRENT set to 2 generations total (not per worker):
    exactly 2 land 'ready', the other 2 are left untouched as residue."""
    _seams(monkeypatch)
    monkeypatch.setattr(gen.settings, "GENERATION_MAX_PER_RUN", 2)  # 2 generations, 4 targets
    sync = uuid4(); _run_row(db, user, sync)
    cands = [_stage(db, user, sync, source_line_key=f"b{i}") for i in range(4)]
    nano = _FakeProvider("nano_banana", _result("nano_banana"))
    _providers(monkeypatch, {"nano_banana": nano, "flux_kontext": _FakeProvider("flux_kontext", None)})
    _verify(monkeypatch, lambda **k: _ok())

    stats = gen.run_photo_generation(user.id, db, sync)

    assert stats.ready == 2 and stats.budget_stopped is True
    for c in cands:
        db.refresh(c)
    ready = [c for c in cands if c.generation_status == "ready"]
    residue = [c for c in cands if c.generation_status is None]
    assert len(ready) == 2 and len(residue) == 2       # budget-denied left for a later run
    run = _run(db, sync)
    assert run.generation_ready == 2 and run.generation_total == 4


# --- generation_armed gate ---------------------------------------------------

def test_generation_armed_true_with_gemini(monkeypatch):
    monkeypatch.setattr(gen.settings, "GEMINI_API_KEY", "k")
    monkeypatch.setattr(gen.settings, "BFL_API_KEY", None)
    monkeypatch.setattr(gen.settings, "FAL_API_KEY", None)
    assert gen.generation_armed() is True       # nano_banana available + verify key


def test_generation_armed_false_without_keys(monkeypatch):
    monkeypatch.setattr(gen.settings, "GEMINI_API_KEY", None)
    monkeypatch.setattr(gen.settings, "BFL_API_KEY", None)
    monkeypatch.setattr(gen.settings, "FAL_API_KEY", None)
    assert gen.generation_armed() is False


# --- self-heal sweep (run_generation_self_heal) ------------------------------

def _item(db, user, **over):
    """A confirmed photo clothing_item whose card fell back to the raw crop."""
    fields = dict(
        user_id=user.id, name="Tee", category="top", color_primary="red",
        source_type="photo", image_url="https://blob/cut.jpg",
        image_status="user_uploaded", generation_status="pending_retry",
    )
    fields.update(over)
    it = ClothingItem(**fields)
    db.add(it); db.commit(); db.refresh(it)
    return it


def test_self_heal_candidate_regenerates(db, user, monkeypatch):
    _seams(monkeypatch)
    sync = uuid4()
    c = _stage(db, user, sync, generation_status="pending_retry")
    _providers(monkeypatch, {
        "nano_banana": _FakeProvider("nano_banana", _result("nano_banana")),
        "flux_kontext": _FakeProvider("flux_kontext", _result("flux_kontext")),
    })
    _verify(monkeypatch, lambda **k: _ok())

    stats = gen.run_generation_self_heal(user.id, db)

    db.refresh(c)
    assert c.generation_status == "ready"
    assert c.generated_image_url == "https://blob/gen.png"
    assert c.image_url == "https://blob/cut.jpg"        # crop (source) untouched
    assert stats.candidates_seen == 1 and stats.ready == 1 and stats.held == 0


def test_self_heal_clothing_item_regenerates(db, user, monkeypatch):
    _seams(monkeypatch)
    it = _item(db, user)
    _providers(monkeypatch, {
        "nano_banana": _FakeProvider("nano_banana", _result("nano_banana")),
        "flux_kontext": _FakeProvider("flux_kontext", _result("flux_kontext")),
    })
    _verify(monkeypatch, lambda **k: _ok())

    stats = gen.run_generation_self_heal(user.id, db)

    db.refresh(it)
    # Confirmed item: the card IS image_url, so success replaces the crop with it.
    assert it.generation_status == "ready"
    assert it.image_url == "https://blob/gen.png"
    assert stats.items_seen == 1 and stats.ready == 1


def test_self_heal_idempotent_skips_ready(db, user, monkeypatch):
    store = _seams(monkeypatch)
    sync = uuid4()
    _stage(db, user, sync, generation_status="ready",
           generated_image_url="https://blob/done.png")
    _item(db, user, generation_status="ready", image_url="https://blob/done.png")
    _providers(monkeypatch, {
        "nano_banana": _FakeProvider("nano_banana", _result("nano_banana")),
        "flux_kontext": _FakeProvider("flux_kontext", _result("flux_kontext")),
    })
    _verify(monkeypatch, lambda **k: _ok())

    stats = gen.run_generation_self_heal(user.id, db)

    assert stats.candidates_seen == 0 and stats.items_seen == 0
    assert store["store"] == 0                          # nothing regenerated/stored


def test_self_heal_both_fail_leaves_pending_retry(db, user, monkeypatch):
    _seams(monkeypatch)
    sync = uuid4()
    c = _stage(db, user, sync, generation_status="pending_retry")
    _providers(monkeypatch, {
        "nano_banana": _FakeProvider("nano_banana", _result("nano_banana")),
        "flux_kontext": _FakeProvider("flux_kontext", _result("flux_kontext")),
    })
    _verify(monkeypatch, lambda **k: _fail())

    stats = gen.run_generation_self_heal(user.id, db)

    db.refresh(c)
    assert c.generation_status == "pending_retry"        # still a target for next sweep
    assert c.generated_image_url is None
    assert stats.held == 1 and stats.ready == 0


def test_self_heal_excludes_current_sync(db, user, monkeypatch):
    _seams(monkeypatch)
    sync = uuid4()
    c = _stage(db, user, sync, generation_status="pending_retry")
    _providers(monkeypatch, {
        "nano_banana": _FakeProvider("nano_banana", _result("nano_banana")),
        "flux_kontext": _FakeProvider("flux_kontext", _result("flux_kontext")),
    })
    _verify(monkeypatch, lambda **k: _ok())

    stats = gen.run_generation_self_heal(user.id, db, exclude_sync_id=sync)

    db.refresh(c)
    assert c.generation_status == "pending_retry"        # this run's fresh failure skipped
    assert stats.candidates_seen == 0


def test_self_heal_scoped_per_user(db, user, monkeypatch):
    _seams(monkeypatch)
    other = User(email="x@example.com", hashed_password="x", display_name="X")
    db.add(other); db.commit(); db.refresh(other)
    _item(db, other)                                     # another user's pending_retry item
    _providers(monkeypatch, {
        "nano_banana": _FakeProvider("nano_banana", _result("nano_banana")),
        "flux_kontext": _FakeProvider("flux_kontext", _result("flux_kontext")),
    })
    _verify(monkeypatch, lambda **k: _ok())

    stats = gen.run_generation_self_heal(user.id, db)

    assert stats.items_seen == 0 and stats.ready == 0    # never touches another user's rows
