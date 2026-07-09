"""Ready-first Phase 1: authoritative candidate pipeline_state + fail-closed person_status

Revision ID: 0035_pipeline_state_person_status
Revises: 0034_generation_attempts
Create Date: 2026-07-09

Two columns that make the READY-FIRST contract enforceable:

1. ingest_candidates.pipeline_state — the authoritative per-candidate readiness state
   machine (staged -> canonicalized -> image_pending -> image_generated -> verified_clean
   -> ready | failed). Server-written at each transition; the review deck and the Home
   banner settle-condition gate STRICTLY on 'ready'. NOT NULL DEFAULT 'staged' so every
   new row starts at the machine's entry state.

2. person_status on BOTH ingest_candidates and clothing_items — the FAIL-CLOSED person
   signal that replaces the bare on_model boolean as the display-mask key. on_model
   conflated "unchecked" with "no person" (its default false read as clean): every Gmail
   row was asserted person-free without any detector ever running. person_status is a
   tri-state: 'unknown' (not affirmatively determined -> MASKED), 'person_present'
   (masked, generation reference only), 'person_free' (affirmatively clean -> showable).
   NOT NULL DEFAULT 'unknown' = fail-closed for every future row whose detector never ran.
   (on_model stays: the photo detector still writes it; person_status is derived alongside.)

BACKFILL (no current row may read "unchecked" as "clean"):
- photo rows (both tables): the photo person-detector ran at stage time and wrote on_model
  affirmatively both ways (person_count>=1 -> true, else false), so on_model is a real
  measurement there: on_model=true -> 'person_present', on_model=false -> 'person_free'.
- gmail rows (both tables): NO person detection ever ran -> 'unknown' (masked). This
  includes rows whose image may in fact be clean — better masked than leaking a person.
- pipeline_state backfill (candidates only): photo candidates with a verified generated
  card (generation_status='ready' AND generated_image_url) -> 'ready'; terminal
  generation_status='failed' -> 'failed'; everything else (all gmail included) -> 'staged'.
  Gmail candidates therefore all start un-ready — intended: nothing Gmail reaches the deck
  until the generation phase (Phase 2) wires the email path to 'ready'.

Named CHECKs (not diffed by autogenerate), ADD COLUMN IF NOT EXISTS keeps re-runs safe.
No RLS change (both tables already per-user). No PII touched.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0035_pipeline_state_person_status"
down_revision = "0034_generation_attempts"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
-- 1. Authoritative readiness state machine (candidates only; items are post-review).
ALTER TABLE public.ingest_candidates
    ADD COLUMN IF NOT EXISTS pipeline_state text NOT NULL DEFAULT 'staged';

-- 2. Fail-closed person signal on both display-bearing tables.
ALTER TABLE public.ingest_candidates
    ADD COLUMN IF NOT EXISTS person_status text NOT NULL DEFAULT 'unknown';
ALTER TABLE public.clothing_items
    ADD COLUMN IF NOT EXISTS person_status text NOT NULL DEFAULT 'unknown';

-- Enum guards (named CHECKs, mirror the ORM __table_args__).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pipeline_state') THEN
        ALTER TABLE public.ingest_candidates ADD CONSTRAINT pipeline_state CHECK (
            pipeline_state IN ('staged','canonicalized','image_pending',
                               'image_generated','verified_clean','ready','failed'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'person_status'
                     AND conrelid = 'public.ingest_candidates'::regclass) THEN
        ALTER TABLE public.ingest_candidates ADD CONSTRAINT person_status CHECK (
            person_status IN ('unknown','person_present','person_free'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'person_status'
                     AND conrelid = 'public.clothing_items'::regclass) THEN
        ALTER TABLE public.clothing_items ADD CONSTRAINT person_status CHECK (
            person_status IN ('unknown','person_present','person_free'));
    END IF;
END $$;

-- 3. Backfill person_status: photo detector output is affirmative both ways; gmail
--    rows had NO detector -> stay 'unknown' (the fail-closed column default).
UPDATE public.ingest_candidates
SET person_status = CASE WHEN on_model THEN 'person_present' ELSE 'person_free' END
WHERE source_type = 'photo';

UPDATE public.clothing_items
SET person_status = CASE WHEN on_model THEN 'person_present' ELSE 'person_free' END
WHERE source_type = 'photo';

-- 4. Backfill pipeline_state: only a verified generated card counts as 'ready'.
UPDATE public.ingest_candidates
SET pipeline_state = CASE
    WHEN generation_status = 'ready' AND generated_image_url IS NOT NULL THEN 'ready'
    WHEN generation_status = 'failed' THEN 'failed'
    ELSE 'staged'
END
WHERE source_type = 'photo';
-- gmail candidates keep the 'staged' default: none are ready until Phase 2.
"""

DOWNGRADE_SQL = r"""
ALTER TABLE public.clothing_items    DROP CONSTRAINT IF EXISTS person_status;
ALTER TABLE public.clothing_items    DROP COLUMN IF EXISTS person_status;
ALTER TABLE public.ingest_candidates DROP CONSTRAINT IF EXISTS person_status;
ALTER TABLE public.ingest_candidates DROP CONSTRAINT IF EXISTS pipeline_state;
ALTER TABLE public.ingest_candidates DROP COLUMN IF EXISTS person_status;
ALTER TABLE public.ingest_candidates DROP COLUMN IF EXISTS pipeline_state;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
