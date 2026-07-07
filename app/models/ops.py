"""Tables that exist live but were previously unmodeled in the ORM.

Modeled here so the ORM and the Alembic baseline agree with the real database.
These are not yet wired into any endpoint; they document the live schema and
unblock future features (weather caching, waitlist).

Split out of the former monolithic app/models.py (P3.2, ARCHITECTURE_AUDIT R4).
Re-exported from app.models for backward compatibility -- see
app/models/__init__.py.
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Double, Index, Integer, String, Text, UniqueConstraint, text

from app.db import Base, GUID
from app.models._shared import _jsonb


class WeatherCache(Base):

    __tablename__ = "weather_cache"

    __table_args__ = (
        Index("idx_weather_cache_expires", "expires_at"),
        Index("idx_weather_cache_lookup", "provider", "lat", "lon", "timezone", "start_at", "end_at"),
        {"comment": "Cache for weather API responses to reduce external API calls"},
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    provider = Column(Text, nullable=False, comment="Weather provider name (e.g., open_meteo)")

    # Live: double precision (float8).
    lat = Column(Double, nullable=False)

    lon = Column(Double, nullable=False)

    timezone = Column(Text, nullable=False)

    start_at = Column(DateTime(timezone=True), nullable=False)

    end_at = Column(DateTime(timezone=True), nullable=False)

    payload = Column(_jsonb(), nullable=False, comment="Cached WeatherForecast JSON payload")

    fetched_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    expires_at = Column(DateTime(timezone=True), nullable=False,
                        comment="When this cache entry expires (UTC)")


class Waitlist(Base):

    __tablename__ = "waitlist"

    __table_args__ = (
        UniqueConstraint("email", name="waitlist_email_key"),
        Index("idx_waitlist_email", "email"),
        # created_at DESC live (recent-first). text() keeps metadata == reflection.
        Index("idx_waitlist_created_at", text('created_at DESC')),
        {"comment": "Stores email addresses of users who joined the waitlist"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    email = Column(String, nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
