"""ingest_candidates generation card + lifecycle; ingest_runs generation counters (Wave 2)

Revision ID: 0016_ingest_candidate_generation
Revises: 0015_photo_detect_sessions
Create Date: 2026-07-02

Wave 2 wires the generation seam into the LIVE photo flow: after a photo commit
stages garment cutouts, a background job turns each cutout into a clean product-card
image via an image-editing model (nano_banana, retry -> flux_kontext), passes it
through the fidelity-verify gate, and stores the VERIFIED result.

Critical constraint (from discovery): a photo candidate is already staged with
image_url = raw cutout and image_status = 'user_uploaded'. Generation is a SECOND
image over an already-populated card, so it gets its OWN fields — never reusing
image_url / image_status:

  ingest_candidates:
    * generated_image_url (text, NULL)  : the verified clean product card. image_url
      stays the crop (verify reference + last-resort). NULL until a generation passes.
    * generation_status (text, NULL)    : generating | ready | failed | pending_retry
      (named CHECK, NULL allowed). NULL = not a generation target (e.g. Gmail rows).
      SEPARATE from image_status, which keeps its own vocabulary.

  ingest_runs (so GET /ingest/status can report generation-in-flight):
    * generation_total  (int NOT NULL DEFAULT 0)  : candidates to generate this run
    * generation_ready  (int NOT NULL DEFAULT 0)  : verified + stored
    * generation_failed (int NOT NULL DEFAULT 0)  : held pending_retry

Conventions reused from 0011/0012: raw SQL via op.execute; ADD COLUMN IF NOT EXISTS +
guarded ADD CONSTRAINT so re-applying is a no-op; the CHECK is auto-named
ingest_candidates_generation_status_check to match the ORM naming convention in
app/db.py, keeping `alembic check` green against app/models.py (the new columns +
CheckConstraint(name='generation_status')). Additive only — no backfill: existing
photo candidates stay NULL (not yet generation targets) until a self-heal sweep runs.

Postgres/Supabase-specific. The optional LOCAL_DB=sqlite dev/test mode never runs
Alembic migrations (it builds the schema from app/models.py via create_all).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0016_ingest_candidate_generation"
down_revision = "0015_photo_detect_sessions"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
-- ingest_candidates: the generated product card + its lifecycle -----------------
ALTER TABLE public.ingest_candidates
    ADD COLUMN IF NOT EXISTS generated_image_url text;

ALTER TABLE public.ingest_candidates
    ADD COLUMN IF NOT EXISTS generation_status text;

-- generation_status enum guard (named CHECK; not diffed by autogenerate). NULL allowed.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'ingest_candidates'
          AND constraint_name = 'ingest_candidates_generation_status_check'
    ) THEN
        ALTER TABLE public.ingest_candidates
            ADD CONSTRAINT ingest_candidates_generation_status_check
            CHECK (generation_status IS NULL OR generation_status IN
                   ('generating','ready','failed','pending_retry'));
    END IF;
END $$;

-- ingest_runs: per-run generation progress counters ----------------------------
ALTER TABLE public.ingest_runs
    ADD COLUMN IF NOT EXISTS generation_total integer NOT NULL DEFAULT 0;

ALTER TABLE public.ingest_runs
    ADD COLUMN IF NOT EXISTS generation_ready integer NOT NULL DEFAULT 0;

ALTER TABLE public.ingest_runs
    ADD COLUMN IF NOT EXISTS generation_failed integer NOT NULL DEFAULT 0;
"""


DOWNGRADE_SQL = r"""
ALTER TABLE public.ingest_runs
    DROP COLUMN IF EXISTS generation_failed;
ALTER TABLE public.ingest_runs
    DROP COLUMN IF EXISTS generation_ready;
ALTER TABLE public.ingest_runs
    DROP COLUMN IF EXISTS generation_total;

ALTER TABLE public.ingest_candidates
    DROP CONSTRAINT IF EXISTS ingest_candidates_generation_status_check;
ALTER TABLE public.ingest_candidates
    DROP COLUMN IF EXISTS generation_status;
ALTER TABLE public.ingest_candidates
    DROP COLUMN IF EXISTS generated_image_url;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
