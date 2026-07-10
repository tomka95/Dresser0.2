"""Receipt-document reconciliation: provenance, demotion, per-run reconcile metrics

Revision ID: 0040_receipt_document
Revises: 0039_generation_observability
Create Date: 2026-07-10

Gmail intake overhaul (Gate 1 approved): extraction now produces a typed receipt
DOCUMENT (email_kind + order block + per-line section evidence) and a deterministic
reconcile pass owns the admit/demote/quarantine decision. This migration adds the
persistence for that decision — nothing here changes behavior on its own.

1. ingest_candidates:
   - provenance jsonb        — per-line evidence: {email_kind, section_evidence,
                               order_evidence, reconciled, stated_item_count}. NULL for
                               pre-0040 rows and non-gmail sources.
   - quarantine_reason text  — machine-readable demotion/quarantine reason (mirrors
                               clothing_items.quarantine_reason, 0038). NULL = not demoted.
   - needs_enrichment bool   — TRUE for a real purchase line created from a fulfillment
                               email whose body carries only variant text ("Black-L"):
                               admitted to the closet but EXCLUDED from image generation
                               until an order-confirmation line supplies the product name.
   - pipeline_state CHECK gains 'rejected_recommendation' — the demoted terminal state
     for recommendation/marketing lines. Deck + settle allowlists gate on 'ready', so
     demoted rows are invisible without further query changes (asserted by tests).

2. processed_messages:
   - email_kind text + CHECK — the Stage-1 document's kind verdict, persisted per message
     (order_confirmation | shipping | delivery | return_or_refund | review_request |
      marketing | other). NULL = not yet re-extracted under the v2 pipeline.
   - filter_reason text      — the Tier-1 keep/drop reason, previously computed and
                               discarded at fetch time.
   - status CHECK gains 'quarantined' — an order_confirmation that reconciled to zero
     admissible lines (invariant alarm): held for re-extraction, never silently dropped.

3. ingest_runs: admitted_count / demoted_count / quarantined_count — per-run reconcile
   metrics (counts only, no content).

Named CHECKs (not diffed by autogenerate); ADD COLUMN IF NOT EXISTS keeps re-runs safe.
The pre-existing CHECKs are dropped + recreated to widen their enum lists. No RLS
change (all three tables already per-user). No PII touched.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0040_receipt_document"
down_revision = "0039_generation_observability"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
-- 1. ingest_candidates: provenance + demotion + enrichment flag.
ALTER TABLE public.ingest_candidates
    ADD COLUMN IF NOT EXISTS provenance jsonb;
ALTER TABLE public.ingest_candidates
    ADD COLUMN IF NOT EXISTS quarantine_reason text;
ALTER TABLE public.ingest_candidates
    ADD COLUMN IF NOT EXISTS needs_enrichment boolean NOT NULL DEFAULT false;

-- Widen pipeline_state with the demoted terminal state.
ALTER TABLE public.ingest_candidates DROP CONSTRAINT IF EXISTS pipeline_state;
ALTER TABLE public.ingest_candidates ADD CONSTRAINT pipeline_state CHECK (
    pipeline_state IN ('staged','canonicalized','image_pending','image_generated',
                       'verified_clean','ready','failed','rejected_recommendation'));

-- 2. processed_messages: persist the kind verdict + Tier-1 reason; add quarantine status.
ALTER TABLE public.processed_messages
    ADD COLUMN IF NOT EXISTS email_kind text;
ALTER TABLE public.processed_messages
    ADD COLUMN IF NOT EXISTS filter_reason text;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'email_kind'
                     AND conrelid = 'public.processed_messages'::regclass) THEN
        ALTER TABLE public.processed_messages ADD CONSTRAINT email_kind CHECK (
            email_kind IS NULL OR email_kind IN
            ('order_confirmation','shipping','delivery','return_or_refund',
             'review_request','marketing','other'));
    END IF;
END $$;

ALTER TABLE public.processed_messages DROP CONSTRAINT IF EXISTS status;
ALTER TABLE public.processed_messages ADD CONSTRAINT status CHECK (
    status IN ('fetched','filtered_out','extracted','confirmed','rejected','error',
               'quarantined'));

-- 3. ingest_runs: reconcile metrics (counts only).
ALTER TABLE public.ingest_runs
    ADD COLUMN IF NOT EXISTS admitted_count integer NOT NULL DEFAULT 0;
ALTER TABLE public.ingest_runs
    ADD COLUMN IF NOT EXISTS demoted_count integer NOT NULL DEFAULT 0;
ALTER TABLE public.ingest_runs
    ADD COLUMN IF NOT EXISTS quarantined_count integer NOT NULL DEFAULT 0;
"""

DOWNGRADE_SQL = r"""
ALTER TABLE public.ingest_runs DROP COLUMN IF EXISTS quarantined_count;
ALTER TABLE public.ingest_runs DROP COLUMN IF EXISTS demoted_count;
ALTER TABLE public.ingest_runs DROP COLUMN IF EXISTS admitted_count;

ALTER TABLE public.processed_messages DROP CONSTRAINT IF EXISTS status;
ALTER TABLE public.processed_messages ADD CONSTRAINT status CHECK (
    status IN ('fetched','filtered_out','extracted','confirmed','rejected','error'));
ALTER TABLE public.processed_messages DROP CONSTRAINT IF EXISTS email_kind;
ALTER TABLE public.processed_messages DROP COLUMN IF EXISTS filter_reason;
ALTER TABLE public.processed_messages DROP COLUMN IF EXISTS email_kind;

ALTER TABLE public.ingest_candidates DROP CONSTRAINT IF EXISTS pipeline_state;
ALTER TABLE public.ingest_candidates ADD CONSTRAINT pipeline_state CHECK (
    pipeline_state IN ('staged','canonicalized','image_pending','image_generated',
                       'verified_clean','ready','failed'));
ALTER TABLE public.ingest_candidates DROP COLUMN IF EXISTS needs_enrichment;
ALTER TABLE public.ingest_candidates DROP COLUMN IF EXISTS quarantine_reason;
ALTER TABLE public.ingest_candidates DROP COLUMN IF EXISTS provenance;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
