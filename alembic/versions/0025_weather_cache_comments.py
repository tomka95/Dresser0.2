"""weather_cache column comments (align schema with the WeatherCache ORM)

Revision ID: 0025_weather_cache_comments
Revises: 0024_wardrobe_gap
Create Date: 2026-07-06

The WeatherCache ORM model declares column comments on provider / payload / expires_at, but
the 0001 baseline created weather_cache WITHOUT them. That mismatch is the only thing
`alembic check` flags after a clean rebuild (a cosmetic comment diff, no structural change).

This migration sets the three comments to match the model exactly, so autogenerate is a
no-op. Pure COMMENT DDL — no data, no lock of consequence, fully reversible (downgrade
clears the comments back to NULL, the pre-0025 state).

Postgres-specific COMMENT syntax; harmless on any Postgres. LOCAL_DB=sqlite dev/test never
runs Alembic.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0025_weather_cache_comments"
down_revision = "0024_wardrobe_gap"
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
COMMENT ON COLUMN public.weather_cache.provider   IS 'Weather provider name (e.g., open_meteo)';
COMMENT ON COLUMN public.weather_cache.payload    IS 'Cached WeatherForecast JSON payload';
COMMENT ON COLUMN public.weather_cache.expires_at IS 'When this cache entry expires (UTC)';
"""

DOWNGRADE_SQL = r"""
COMMENT ON COLUMN public.weather_cache.provider   IS NULL;
COMMENT ON COLUMN public.weather_cache.payload    IS NULL;
COMMENT ON COLUMN public.weather_cache.expires_at IS NULL;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
