"""Dev / nightly re-distill: decay + recompute + narrative over the preference substrate.

Usage (from project root):
    python -m scripts.dev_redistill <email>            # one user
    python -m scripts.dev_redistill --all              # every user with a signal or preference
    python -m scripts.dev_redistill <email> --no-narrative   # decay+recompute only (free, no LLM)

WHAT IT DOES
------------
Runs app.services.stylist.distill.run_redistill for each user — the nightly half of
the S3 learning core (the eager half, chat distillation, runs per-session inside the
chat endpoint). For each user it:

  1. DECAY     — ages every style_preferences.confidence by how long it has gone
                 un-reinforced (confidence *= exp(-λ·Δt), Δt from last_seen_at). An
                 INFERRED preference below the active floor is flipped active=false;
                 explicit/onboarding preferences are never auto-deactivated.
  2. RECOMPUTE — aggregates preference_signals (weighted by source strength × per-
                 signal decay) into typed style_preferences. An inferred recompute
                 NEVER overwrites a user-stated (explicit/onboarding) preference.
  3. NARRATIVE — regenerates style_profiles.narrative_blob (2-3 sentences) from the
                 typed active preferences + recent session summaries, then bumps
                 version + distilled_at. This is the only LLM call per user.

Decay + recompute are pure-Python and free; the narrative pass is the only paid
step and is budget-capped (DISTILL_MAX_NARRATIVE_CALLS_PER_RUN across an --all
sweep; --no-narrative skips it entirely). Idempotent-ish: re-running the same night
decays a hair more and re-asserts the same preferences. There is NO in-app
scheduler — run from cron / by hand, like the enrichment backfill.
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
logging.getLogger("httpcore").setLevel(logging.WARNING)

from app.core.config import settings
from app.db import SessionLocal
from app.models import PreferenceSignal, StylePreference, User
from app.services.stylist.distill import RedistillStats, run_redistill


def _print_stats(email: str, s: RedistillStats) -> None:
    print(f"\n  {email}")
    print(f"    preferences seen:        {s.prefs_seen}")
    print(f"    decayed / deactivated:   {s.decayed} / {s.deactivated}")
    print(f"    signals aggregated:      {s.signals_seen}")
    print(f"    preferences upserted:    {s.prefs_upserted}")
    print(f"    protected (explicit won): {s.prefs_protected}")
    print(f"    narrative regenerated:   {s.narrative_regenerated}")
    print(f"    cost: ${s.cost_usd:.5f}    elapsed: {s.elapsed:.2f}s")
    if s.error:
        print(f"    NOTE: run errored ({s.error}) — left as-is, rolled back.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m scripts.dev_redistill")
    parser.add_argument("email", nargs="?", help="User email (omit with --all)")
    parser.add_argument("--all", action="store_true",
                        help="Re-distill EVERY user that has a preference or signal row.")
    parser.add_argument("--no-narrative", action="store_true",
                        help="Skip the LLM narrative pass (decay+recompute only, free).")
    args = parser.parse_args()

    if not args.all and not args.email:
        parser.error("provide an <email> or --all")

    db = SessionLocal()
    try:
        if args.all:
            # Any user with substrate to re-distill (a preference OR a raw signal).
            pref_uids = {u for (u,) in db.query(StylePreference.user_id).distinct()}
            sig_uids = {u for (u,) in db.query(PreferenceSignal.user_id).distinct()}
            uids = pref_uids | sig_uids
            if not uids:
                print("No users with preferences or signals found.")
                return
            emails = dict(
                db.query(User.id, User.email).filter(User.id.in_(uids)).all()
            )
            user_ids = [(emails.get(u, str(u)), u) for u in uids]
        else:
            user = db.query(User).filter(User.email == args.email.strip()).first()
            if not user:
                print(f"ERROR: no user with email {args.email!r}")
                sys.exit(1)
            user_ids = [(user.email, user.id)]

        print(f"Re-distill over {len(user_ids)} user(s)"
              f"{' (no narrative)' if args.no_narrative else ''}…")

        narrative_budget = settings.DISTILL_MAX_NARRATIVE_CALLS_PER_RUN
        totals = {"upserted": 0, "deactivated": 0, "narrative": 0, "cost": 0.0}
        for email, uid in user_ids:
            do_narrative = (not args.no_narrative) and narrative_budget > 0
            s = run_redistill(db, uid, regenerate_narrative_blob=do_narrative)
            # Commit per user so one user's failure never rolls back the batch.
            db.commit()
            _print_stats(email, s)
            if s.narrative_regenerated:
                narrative_budget -= 1
                totals["narrative"] += 1
            totals["upserted"] += s.prefs_upserted
            totals["deactivated"] += s.deactivated
            totals["cost"] += s.cost_usd

        print("\n" + "=" * 56)
        print("  RE-DISTILL SUMMARY")
        print("=" * 56)
        print(f"  users processed:       {len(user_ids)}")
        print(f"  preferences upserted:  {totals['upserted']}")
        print(f"  preferences deactivated: {totals['deactivated']}")
        print(f"  narratives regenerated: {totals['narrative']}")
        print(f"  total cost:            ${totals['cost']:.5f}")
        print("=" * 56)

    except KeyboardInterrupt:
        print("\nInterrupted.")
        db.rollback()
        sys.exit(130)
    finally:
        db.close()


if __name__ == "__main__":
    main()
