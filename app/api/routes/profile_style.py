"""GET/PATCH /profile/style — the "My Style Profile" screen's data.

Identity is the JWT subject (get_current_user), NEVER a request-body field. All
DB work runs inside ``rls_scoped_session(current_user.id)`` — the SAME RLS-pinned
path the stylist agent reads style_profiles / style_preferences through — so
Postgres itself enforces per-user isolation on top of the app-level WHERE. There
is no user_id in the path: a caller can only ever read/write their OWN profile.

Writes are sacred (user_edited stamp) and deletes are tombstones; the durable
design lives in app.services.style_profile_service.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.dependencies import get_current_user
from app.models import User
from app.services.onboarding_service import OnboardingValidationError
from app.services.stylist.rls import RlsSetupError, rls_scoped_session
from app.services.style_profile_service import (
    StyleProfileValidationError,
    apply_facts_edit,
    apply_preference_override,
    read_style_profile,
    tombstone_preference,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profile/style", tags=["profile"])


# --- Wire schemas (camelCase out; the facts blob passes through as-is) --------
class PreferenceOut(BaseModel):
    dimension: str
    value: Dict[str, Any] = Field(default_factory=dict)
    polarity: Optional[str] = None
    confidence: Optional[float] = None
    evidenceCount: int = 0
    source: Optional[str] = None
    userEdited: bool = False
    lastReinforcedAt: Optional[str] = None
    explanation: str = ""


class StyleProfileOut(BaseModel):
    facts: Dict[str, Any] = Field(default_factory=dict)
    narrative: Optional[str] = None
    summary: Optional[str] = None
    onboardingCompletedAt: Optional[str] = None
    version: int = 0
    preferences: List[PreferenceOut] = Field(default_factory=list)


class PreferenceEditIn(BaseModel):
    """One preference change. Either an override (set polarity/value) or a
    delete=True tombstone, keyed by the typed dimension."""

    model_config = ConfigDict(extra="forbid")

    dimension: str
    polarity: Optional[str] = None
    value: Optional[Dict[str, Any]] = None
    delete: bool = False


class StyleProfilePatchIn(BaseModel):
    """User edits: a partial facts merge and/or a list of preference changes.
    Unknown/ server-owned fields are ignored so a client can't inject them."""

    model_config = ConfigDict(extra="ignore")

    facts: Optional[Dict[str, Any]] = None
    preferences: Optional[List[PreferenceEditIn]] = None


def _read(user_id) -> StyleProfileOut:
    with rls_scoped_session(user_id) as db:
        payload = read_style_profile(db, user_id)
    return StyleProfileOut(**payload)


@router.get("", response_model=StyleProfileOut)
def get_style_profile(current_user: User = Depends(get_current_user)) -> StyleProfileOut:
    try:
        return _read(current_user.id)
    except RlsSetupError as exc:
        logger.error("RLS setup failed for style profile read: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile temporarily unavailable.",
        )


@router.patch("", response_model=StyleProfileOut)
def patch_style_profile(
    body: StyleProfilePatchIn,
    current_user: User = Depends(get_current_user),
) -> StyleProfileOut:
    user_id = current_user.id
    try:
        with rls_scoped_session(user_id) as db:
            if body.facts is not None:
                apply_facts_edit(db, user_id, body.facts)
            for edit in body.preferences or []:
                if edit.delete:
                    tombstone_preference(db, user_id, edit.dimension)
                else:
                    apply_preference_override(
                        db, user_id, edit.dimension,
                        polarity=edit.polarity, value=edit.value,
                    )
            # commit happens on clean context exit; read back in the SAME txn.
            payload = read_style_profile(db, user_id)
        return StyleProfileOut(**payload)
    except (StyleProfileValidationError, OnboardingValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except RlsSetupError as exc:
        logger.error("RLS setup failed for style profile write: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile temporarily unavailable.",
        )
