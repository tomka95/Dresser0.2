"""Shared SQLAlchemy column-type helpers used across the models/ package.

Split out of the former monolithic app/models.py (P3.2, ARCHITECTURE_AUDIT R4).
Kept in its own module (not any one context file) so every context module
(user, closet, ingestion, image, stylist, ranking, monetization, ops) can
import these without creating a cross-context dependency.
"""
from sqlalchemy import DateTime, JSON, Text
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY, JSONB, UUID as PG_UUID
from pgvector.sqlalchemy import Vector


# Timestamp helper: the live DB uses `timestamp with time zone` for nearly every
# timestamp column. Use this so ORM metadata matches and autogenerate stays clean.
def _tstz(**kw):
    return DateTime(timezone=True)


# --- Cross-dialect column helpers -------------------------------------------
# Production runs on PostgreSQL (Supabase); the optional LOCAL_DB=sqlite dev mode
# needs the same models to map cleanly. These mirror the intent of the GUID type:
# the real Postgres column type, with a portable SQLite fallback.
#
# Note: server-side defaults (e.g. ''{}''::text[], gen_random_uuid()) live in the
# Alembic baseline migration, which owns the schema. The Python-side defaults below
# keep ORM inserts working on both dialects without emitting Postgres-only DDL.
def _jsonb():
    return JSONB().with_variant(JSON(), "sqlite")


def _text_array():
    return PG_ARRAY(Text()).with_variant(JSON(), "sqlite")


def _uuid_array():
    # Postgres uuid[]; JSON fallback under the SQLite dev/test create_all() path.
    return PG_ARRAY(PG_UUID(as_uuid=True)).with_variant(JSON(), "sqlite")


# pgvector column (Postgres `vector(dim)`), with a portable SQLite fallback so the
# LOCAL_DB=sqlite dev/test create_all() path doesn't choke on the vector type (tests
# never read/write embeddings). dim is fixed at DDL time; see EMBEDDING_DIM in config.
def _vector(dim):
    return Vector(dim).with_variant(Text(), "sqlite")
