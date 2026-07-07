import logging
from typing import Any, Dict
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import User
from .supabase_auth import (
    SupabaseAuthError,
    verify_supabase_token,
)

logger = logging.getLogger(__name__)

security = HTTPBearer()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated user from a Supabase Auth access token.

    Supabase Auth is the ONLY identity path. Access tokens are asymmetric JWTs
    (ES256/RS256/EdDSA) verified against the project's public JWKS; the signature
    plus the `iss`, `aud`, and `exp` claims are all checked (see
    app.supabase_auth.verify_supabase_token). The user is resolved by Supabase
    user id (`sub`); if no public.users profile row exists yet, one is
    auto-provisioned.

    The legacy custom HS256-JWT dual-accept path was RETIRED (auth-hardening
    S1): symmetric/custom tokens are rejected, there is no shared secret to
    forge, and if Supabase Auth is not configured the request fails CLOSED
    (401) rather than falling back to any forgeable key.

    Raises HTTPException(401) on any failure.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        claims = verify_supabase_token(credentials.credentials)
    except SupabaseAuthError as exc:
        # Covers unconfigured Supabase, bad signature, wrong iss/aud, expiry,
        # unknown kid, and any non-asymmetric (HS256/custom) or malformed token.
        logger.info("Auth rejected: %s", exc)
        raise credentials_exception

    return _resolve_supabase_user(db, claims, credentials_exception)


def _resolve_supabase_user(
    db: Session,
    claims: Dict[str, Any],
    credentials_exception: HTTPException,
) -> User:
    """Resolve (or auto-provision) the public.users profile for a Supabase user.

    The Supabase `sub` is the auth.users id and becomes the public.users primary
    key (see the users.id -> auth.users(id) FK migration). If no profile row
    exists yet, create one on first authenticated request.
    """
    sub = claims.get("sub")
    try:
        user_uuid = UUID(str(sub))
    except (ValueError, TypeError):
        logger.warning("Supabase token 'sub' is not a valid UUID: %r", sub)
        raise credentials_exception

    user = db.query(User).filter(User.id == user_uuid).first()
    if user is not None:
        return user

    # Auto-provision a profile keyed to the Supabase user id.
    email = claims.get("email")
    metadata = claims.get("user_metadata") or {}
    full_name = metadata.get("full_name") or metadata.get("name")
    avatar_url = metadata.get("avatar_url") or metadata.get("picture")

    user = User(
        id=user_uuid,
        # users.email is NOT NULL + UNIQUE. Supabase access tokens normally carry
        # an email; fall back to a stable, unique placeholder if one is absent
        # (e.g. phone-only sign-ups) so provisioning never violates NOT NULL.
        email=email or f"{user_uuid}@users.noreply.supabase",
        # hashed_password is NOT NULL and not yet dropped (legacy path still live).
        # Supabase-provisioned profiles authenticate via Supabase, never via this
        # column, so store an empty sentinel — matching the existing OAuth path.
        hashed_password="",
        full_name=full_name,
        display_name=full_name,
        avatar_url=avatar_url,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Concurrent provisioning of the same id, or an existing profile that owns
        # this email under a different id (a legacy account not yet linked to
        # Supabase). Account linking is deferred to a later phase; for now resolve
        # to whatever row already exists so the request succeeds.
        db.rollback()
        existing = db.query(User).filter(User.id == user_uuid).first()
        if existing is None and email is not None:
            existing = db.query(User).filter(User.email == email).first()
            if existing is not None:
                logger.warning(
                    "Supabase user %s shares email %s with existing profile %s "
                    "(id mismatch). Resolving to existing profile; account "
                    "linking is deferred.",
                    user_uuid,
                    email,
                    existing.id,
                )
        if existing is None:
            logger.error("Failed to provision profile for Supabase user %s", user_uuid)
            raise credentials_exception
        return existing

    db.refresh(user)
    logger.info("Auto-provisioned public.users profile for Supabase user %s", user_uuid)
    return user
