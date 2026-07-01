"""Dev proof: exercise the phase-3d-a swipe-review confirm flow end-to-end.

Usage (from project root):
    python -m scripts.dev_confirm_ingest <email>

WHAT IT PROVES (against the user's already-staged status='pending' candidates):
  1. accept a SUBSET, reject a SUBSET, and EDIT one field on an accepted candidate;
  2. accepted candidates appear in clothing_items, deduped on source_line_key, with
     the edit applied;
  3. rejected candidates write NOTHING to clothing_items;
  4. candidate statuses flip to 'accepted' / 'rejected';
  5. a SECOND identical confirm creates ZERO new clothing_items (ON CONFLICT) — the
     before/after closet count is unchanged and inserted_count is 0.

It calls the SAME service the HTTP route calls (confirm_candidates) directly — no
HTTP, no JWT — with user_id resolved from <email>. It writes to clothing_items via
the confirm path ONLY (exactly what the endpoint does). Nothing else is mutated
beyond candidate statuses + the accepted closet rows.
"""
from __future__ import annotations

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logging.getLogger("httpx").setLevel(logging.WARNING)

from app.db import SessionLocal
from app.gmail_closet.review_service import confirm_candidates, list_pending_candidates
from app.models import ClothingItem, IngestCandidate, User

# A recognizable edit applied to ONE accepted candidate's size, so we can prove the
# edit reaches clothing_items (and survives a re-confirm).
_EDIT_FIELD = "size"
_EDIT_VALUE = "DEV-EDIT"


def _closet_count(db, user_id) -> int:
    return db.query(ClothingItem).filter(ClothingItem.user_id == user_id).count()


def _row_for_key(db, user_id, source_line_key):
    return (
        db.query(ClothingItem)
        .filter(
            ClothingItem.user_id == user_id,
            ClothingItem.source_line_key == source_line_key,
        )
        .first()
    )


def _print_written(written) -> None:
    print(f"\n  Written clothing_items rows ({len(written)}):")
    if not written:
        print("    (none)")
        return
    print(f"    {'INS/UPD':9}{'NAME':30}{'SOURCE_LINE_KEY':34}")
    print("    " + "─" * 72)
    for w in written:
        tag = "INSERT" if w.inserted else "update"
        name = (w.name or "—")[:29]
        print(f"    {tag:9}{name:30}{(w.source_line_key or '—')[:34]}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m scripts.dev_confirm_ingest")
    parser.add_argument("email", help="User email (must exist; have staged candidates)")
    args = parser.parse_args()
    email = args.email.strip()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"ERROR: no user with email {email!r}")
            sys.exit(1)

        print(f"\nUser:    {email}")
        print(f"user_id: {user.id}")

        # ----------------------------------------------------------------
        # The pending deck (same service GET /gmail/ingest/candidates uses)
        # ----------------------------------------------------------------
        deck = list_pending_candidates(db, user.id)
        print(f"\nPending candidates (swipe deck): {len(deck)}")
        if deck:
            sample = deck[0]
            print("  sample card (GET /candidates shape):")
            for k in ("candidate_id", "name", "brand", "category", "color", "size",
                      "qty", "unit_price", "currency", "order_date", "confidence_overall",
                      "low_confidence_fields", "seen_count"):
                print(f"    {k:22}= {sample.get(k)}")
            print(f"    {'source':22}= {sample.get('source')}")

        # Pull the matching ORM rows so we can read source_line_key for verification
        # (the API view deliberately omits the internal dedup key).
        pending = (
            db.query(IngestCandidate)
            .filter(
                IngestCandidate.user_id == user.id,
                IngestCandidate.status == "pending",
            )
            .order_by(
                IngestCandidate.confidence_overall.desc().nullslast(),
                IngestCandidate.created_at.desc(),
            )
            .all()
        )
        if len(pending) < 1:
            print("\nERROR: no pending candidates to confirm. Run the extraction pass first:")
            print(f"       python -m scripts.dev_run_ingest {email}")
            sys.exit(1)

        # ----------------------------------------------------------------
        # Choose: accept ~half, reject ~half of the rest, edit one accepted
        # ----------------------------------------------------------------
        n = len(pending)
        n_accept = max(1, n // 2)
        accept_rows = pending[:n_accept]
        remaining = pending[n_accept:]
        n_reject = max(1, len(remaining) // 2) if remaining else 0
        reject_rows = remaining[:n_reject]
        # Anything not chosen stays pending — proving the deck shrinks, not clears.

        accepted_ids = [str(c.id) for c in accept_rows]
        rejected_ids = [str(c.id) for c in reject_rows]
        edit_target = accepted_ids[0]
        edits = {edit_target: {_EDIT_FIELD: _EDIT_VALUE}}

        accept_keys = {c.id: c.source_line_key for c in accept_rows}
        reject_keys = {c.id: c.source_line_key for c in reject_rows}
        edit_key = accept_keys[accept_rows[0].id]

        print(f"\nPlan: accept {len(accepted_ids)}, reject {len(rejected_ids)}, "
              f"leave {n - len(accepted_ids) - len(rejected_ids)} pending.")
        print(f"      edit candidate {edit_target} -> {_EDIT_FIELD}={_EDIT_VALUE!r}")

        before = _closet_count(db, user.id)
        print(f"\nclothing_items BEFORE: {before}")

        # ----------------------------------------------------------------
        # Confirm #1
        # ----------------------------------------------------------------
        r1 = confirm_candidates(
            db, user.id, accepted=accepted_ids, rejected=rejected_ids, edits=edits
        )
        after1 = _closet_count(db, user.id)
        print(f"\n── Confirm #1 ──")
        print(f"  accepted={r1.accepted_count} rejected={r1.rejected_count} "
              f"inserted={r1.inserted_count} updated={r1.updated_count}")
        print(f"clothing_items AFTER #1: {after1}  (Δ +{after1 - before})")
        _print_written(r1.written)

        # ----------------------------------------------------------------
        # VERIFY
        # ----------------------------------------------------------------
        problems: list[str] = []

        # (a) every accepted candidate has a clothing_items row on its source_line_key
        for cid, key in accept_keys.items():
            if _row_for_key(db, user.id, key) is None:
                problems.append(f"accepted candidate {cid} missing from clothing_items (key={key})")

        # (b) the edit landed
        edited_row = _row_for_key(db, user.id, edit_key)
        if edited_row is None:
            problems.append("edited candidate's row not found")
        elif (getattr(edited_row, _EDIT_FIELD) or "") != _EDIT_VALUE:
            problems.append(
                f"edit NOT applied: clothing_items.{_EDIT_FIELD}="
                f"{getattr(edited_row, _EDIT_FIELD)!r} (expected {_EDIT_VALUE!r})"
            )

        # (c) rejected candidates wrote nothing (skip keys that coincide with an accept)
        accepted_key_set = set(accept_keys.values())
        for cid, key in reject_keys.items():
            if key in accepted_key_set:
                continue
            if _row_for_key(db, user.id, key) is not None:
                problems.append(f"rejected candidate {cid} leaked into clothing_items (key={key})")

        # (d) candidate statuses flipped
        db.expire_all()
        for cid in accept_keys:
            st = db.query(IngestCandidate.status).filter(IngestCandidate.id == cid).scalar()
            if st != "accepted":
                problems.append(f"candidate {cid} status={st!r} (expected 'accepted')")
        for cid in reject_keys:
            st = db.query(IngestCandidate.status).filter(IngestCandidate.id == cid).scalar()
            if st != "rejected":
                problems.append(f"candidate {cid} status={st!r} (expected 'rejected')")

        # ----------------------------------------------------------------
        # Confirm #2 — identical request must create ZERO new rows
        # ----------------------------------------------------------------
        r2 = confirm_candidates(
            db, user.id, accepted=accepted_ids, rejected=rejected_ids, edits=edits
        )
        after2 = _closet_count(db, user.id)
        print(f"\n── Confirm #2 (identical) ──")
        print(f"  accepted={r2.accepted_count} rejected={r2.rejected_count} "
              f"inserted={r2.inserted_count} updated={r2.updated_count}")
        print(f"clothing_items AFTER #2: {after2}  (Δ from #1: {after2 - after1})")

        if r2.inserted_count != 0:
            problems.append(f"re-confirm inserted {r2.inserted_count} NEW rows (expected 0)")
        if after2 != after1:
            problems.append(f"closet count changed on re-confirm: {after1} -> {after2}")

        # ----------------------------------------------------------------
        # Verdict
        # ----------------------------------------------------------------
        print("\n" + "=" * 60)
        if problems:
            print("✗  CONFIRM PROOF FAILED")
            for p in problems:
                print(f"   - {p}")
            print("=" * 60)
            sys.exit(1)
        print("✓  CONFIRM PROOF PASSED")
        print(f"   accepted={r1.accepted_count} -> clothing_items (deduped, edit applied)")
        print(f"   rejected={r1.rejected_count} -> wrote nothing")
        print(f"   statuses flipped; re-confirm added 0 rows (count stable at {after2})")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    finally:
        db.close()


if __name__ == "__main__":
    main()
