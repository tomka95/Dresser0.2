# `migrations/` — superseded by Alembic

These hand-written `.sql` files predate Alembic and are **no longer the schema
source of truth**. Their intent has been folded into the Alembic baseline
(`alembic/versions/0001_baseline_live_schema.py`):

- `add_closet_indexes.sql` → the `idx_clothing_items_*` / `idx_item_images_*`
  indexes are part of the baseline.
- `add_gmail_sync_completed_at.sql` → `users.gmail_sync_completed_at` is part of
  the baseline.

They are kept here only for historical reference. **Do not apply them manually.**
All schema changes now go through Alembic — see the repo `README`/`alembic/`.
