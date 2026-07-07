"""User / identity model (public.users -- the Supabase Auth profile table).

Split out of the former monolithic app/models.py (P3.2, ARCHITECTURE_AUDIT R4).
Re-exported from app.models for backward compatibility -- see
app/models/__init__.py.
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db import Base, GUID
from app.models._shared import _tstz


class User(Base):

    __tablename__ = "users"

    # Live uses UNIQUE constraints (users_email_key / users_google_sub_key), not
    # the auto-named ix_* indexes that Column(unique=True, index=True) would create.
    __table_args__ = (
        UniqueConstraint("email", name="users_email_key"),
        UniqueConstraint("google_sub", name="users_google_sub_key"),
    )


    # Supabase Auth transition: public.users is a PROFILE table whose id equals the
    # corresponding auth.users id. The FK users.id -> auth.users(id) is added by
    # Alembic revision 0002 and is owned exclusively by that migration -- it is NOT
    # declared here, because auth.users is a Supabase/Postgres-only table that must
    # not be a mapped model (modeling it would break create_all() under the SQLite
    # dev/test mode). alembic/env.py::_include_object excludes this FK from
    # autogenerate so the ORM<->live parity stays clean. The uuid4 default remains
    # for the legacy custom-JWT signup path; Supabase-provisioned profiles set id
    # explicitly to the token's `sub`.
    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    # Live: email is `character varying`; the rest are `text`.
    email = Column(String, nullable=False)

    hashed_password = Column(Text, nullable=False)

    display_name = Column(Text, nullable=True)

    google_sub = Column(Text, nullable=True)

    full_name = Column(Text, nullable=True)

    avatar_url = Column(Text, nullable=True)

    created_at = Column(_tstz(), default=datetime.utcnow, nullable=False)

    gmail_sync_completed_at = Column(DateTime(timezone=True), nullable=True)


    clothing_items = relationship("ClothingItem", back_populates="user", cascade="all, delete-orphan")

    google_account = relationship("GoogleAccount", back_populates="user", uselist=False)
