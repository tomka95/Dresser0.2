"""clothing_items.category NOT NULL — the hard backstop for the canonicalization chokepoint

Revision ID: 0030_clothing_items_category_not_null
Revises: 0029_todays_look
Create Date: 2026-07-08

Fix 2+3 (Phase A). Every write into clothing_items now funnels through the ONE
canonicalization chokepoint (app.services.closet_canonicalize), which guarantees a
non-null category. This migration makes the DB enforce that invariant:

  1. BACKFILL every existing null / blank category FIRST — deterministic keyword rules
     over the item name (no LLM in a migration), then 'other' as the catch-all. Runs on
     every dialect (plain UPDATEs).
  2. THEN ALTER COLUMN category SET NOT NULL — Postgres only. The SQLite dev/test DB gets
     the constraint from the ORM model (category = Column(..., nullable=False)) via
     Base.metadata.create_all, so the ALTER is a Postgres-only concern; guarding it keeps
     a non-Supabase / SQLite run a clean no-op (mirrors the auth-schema guards in 0027/0029).

The category CHECK from 0018 (canonical-12 + legacy aliases + 'other') is unchanged; every
value the backfill writes is inside it. Ordering matters: the constraint flip comes AFTER
the backfill so it can never fail on a pre-existing null. `alembic check` is clean after
upgrade (the ORM models the column nullable=False 1:1).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0030_clothing_items_category_not_null"
down_revision = "0029_todays_look"
branch_labels = None
depends_on = None


# Deterministic name -> category rules for the backfill, most-specific first. Each UPDATE
# is guarded by "still null/blank", so an earlier (more specific) rule wins and a later one
# never overwrites it. Conservative, high-precision patterns only; anything unmatched falls
# through to the 'other' catch-all. All categories are inside the 0018 CHECK vocabulary.
_BACKFILL_RULES = [
    ("%sneaker%", "footwear"), ("%shoe%", "footwear"), ("%boot%", "footwear"),
    ("%loafer%", "footwear"), ("%sandal%", "footwear"), ("%heels%", "footwear"),
    ("%blazer%", "outerwear"), ("%jacket%", "outerwear"), ("%overcoat%", "outerwear"),
    ("%trench%", "outerwear"), ("%parka%", "outerwear"), ("%coat%", "outerwear"),
    ("%hoodie%", "top"), ("%sweatshirt%", "top"),
    ("%dress%", "dress"), ("%gown%", "dress"),
    ("%jean%", "bottom"), ("%trouser%", "bottom"), ("%chino%", "bottom"),
    ("%shorts%", "bottom"), ("%skirt%", "bottom"), ("%legging%", "bottom"),
    ("%t-shirt%", "top"), ("%tshirt%", "top"), ("%blouse%", "top"), ("%polo%", "top"),
    ("%sweater%", "top"), ("%cardigan%", "top"), ("%shirt%", "top"),
    ("%backpack%", "bag"), ("%handbag%", "bag"), ("%tote%", "bag"),
    ("%sunglass%", "accessory"), ("%scarf%", "accessory"), ("%beanie%", "accessory"),
    ("%necklace%", "jewelry"), ("%bracelet%", "jewelry"), ("%earring%", "jewelry"),
]

_NULL_OR_BLANK = "(category IS NULL OR trim(category) = '')"


def upgrade() -> None:
    bind = op.get_bind()

    # 1) BACKFILL (all dialects). Keyword rules over the name, then 'other'.
    for pattern, category in _BACKFILL_RULES:
        op.execute(
            f"UPDATE clothing_items SET category = '{category}' "
            f"WHERE {_NULL_OR_BLANK} AND lower(name) LIKE '{pattern}'"
        )
    op.execute(f"UPDATE clothing_items SET category = 'other' WHERE {_NULL_OR_BLANK}")

    # 2) Enforce NOT NULL — Postgres only (SQLite gets it from the ORM model's create_all).
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE clothing_items ALTER COLUMN category SET NOT NULL")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE clothing_items ALTER COLUMN category DROP NOT NULL")
    # The backfilled values are intentionally left in place (the pre-backfill nulls are not
    # recoverable and 'other'/inferred categories are harmless).
