"""Account deletion — real, irreversible erasure of ONE user's data.

App Store Guideline 5.1.1 + GDPR "right to erasure": a signed-in user can delete
their own account and everything Tailor stored about them. This module is the
server-side orchestrator behind ``DELETE /account``.

It runs with the app's normal (owner-role) DB session on purpose: the caller is
the verified owner of the account (their own Supabase JWT drives the request),
and erasing every row a user owns is exactly the case where RLS scoping would get
in the way. There is NO soft-delete / tombstone — rows are gone.

Ordering (matches the endpoint contract):
  1. Revoke the user's Google grants (Gmail + Calendar) AT Google, while their
     encrypted refresh tokens still exist in our DB.
  2. Delete their Storage objects (all images live under the ``{user_id}/`` key
     prefix in the one bucket).
  3. Erase their DB rows — one transaction, explicit per-table deletes in FK-safe
     order (this also cancels any pending/running jobs by removing the job rows).
  4. Delete the Supabase Auth (``auth.users``) identity via the GoTrue Admin API,
     so their sessions/refresh tokens die and the login can never be reused.

Crash-resume / idempotency (design note):
  Every step is individually idempotent and re-runnable, so there is no separate
  "deletion status" column to strand (that would itself be retained user data and
  a form of soft-delete). If the process dies between steps, the client simply
  retries ``DELETE /account``:
    * revoke   — reads whatever token rows still exist; none left ⇒ no-op.
    * storage  — lists remaining objects under the prefix; none ⇒ no-op.
    * DB erase — ``DELETE ... WHERE user_id = :id`` matches 0 rows on a second run,
                 and the whole erase is ONE transaction, so a crash mid-erase rolls
                 back rather than leaving a half-deleted account.
    * identity — GoTrue returns 404 for an already-deleted user ⇒ treated as done.
  The endpoint only reports success once the terminal state (user row gone) is
  reached; a partial failure surfaces as an error and leaves a re-runnable state.

Shared-cache exception (product rule): ``product_image_cache`` and ``image_blobs``
hold cross-user PRODUCT identity (retailer imagery keyed by content hash / cache
key), never a user's own uploads — so they are deliberately NOT in the delete set.
The user's OWN storage objects (under their id prefix) are still erased in step 2.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple
from uuid import UUID

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.token_crypto import TokenCryptoError, decrypt_token
from app.models import (
    CalendarAccount,
    ChatMessage,
    ChatRateWindow,
    ChatUsage,
    ClothingItem,
    Conversation,
    GoogleAccount,
    IngestCandidate,
    IngestRun,
    ItemEmbedding,
    ItemImage,
    Job,
    PhotoDetectSession,
    PhotoUsage,
    PreferenceSignal,
    ProcessedMessage,
    ProcessedUpload,
    ProductClick,
    SavedOutfit,
    StyleEvent,
    StylePreference,
    StyleProfile,
    TodaysLookCache,
    User,
    UserWardrobeGap,
)

logger = logging.getLogger(__name__)

_GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"

# Every user-owning table, children before parents, so the explicit deletes never
# violate a FK even on SQLite (where DB-level ON DELETE CASCADE does NOT fire — the
# foreign_keys pragma is off — and most tables have no ORM delete cascade). On
# Postgres these same rows would also cascade from ``users``; deleting them
# explicitly makes the erasure deterministic and driver-agnostic. ``item_images``
# is the ONE user-data table without a ``user_id`` (it hangs off clothing_items);
# it is handled first, by subquery, in ``delete_user_db_rows``.
#
# Kept intentionally OUT of this list (shared / non-user data): products,
# product_embeddings, product_image_cache, image_blobs, weather_cache, waitlist,
# affiliate_conversions (a commission ledger with no user_id; its click_id is set
# NULL when the user's product_clicks rows go).
_USER_TABLE_DELETE_ORDER: List[Any] = [
    ItemEmbedding,
    PreferenceSignal,
    StyleEvent,
    ChatMessage,
    ProductClick,
    IngestCandidate,
    IngestRun,
    PhotoDetectSession,
    PhotoUsage,
    ProcessedMessage,
    ProcessedUpload,
    ChatRateWindow,
    ChatUsage,
    SavedOutfit,
    StylePreference,
    StyleProfile,
    TodaysLookCache,
    UserWardrobeGap,
    CalendarAccount,
    Job,
    Conversation,   # after ChatMessage
    ClothingItem,   # after ItemEmbedding + ItemImage
    GoogleAccount,  # after ClothingItem (clothing_items.source_google_account_id → SET NULL)
]


def _revoke_one(encrypted_refresh: str | None, field: str, user_id: UUID) -> None:
    """Best-effort revoke of a single encrypted refresh token at Google.

    Never raises and never logs token material: a Google-side failure must not
    strand the user with an un-deletable account (the local rows are erased
    regardless in the DB step).
    """
    if not encrypted_refresh:
        return
    try:
        refresh_plain = decrypt_token(encrypted_refresh, field="refresh_token")
        httpx.post(
            _GOOGLE_REVOKE_ENDPOINT,
            data={"token": refresh_plain},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10.0,
        )
    except (TokenCryptoError, Exception):  # noqa: BLE001 — wipe proceeds regardless
        logger.warning("Account-deletion: %s revoke failed for user %s (continuing)", field, user_id)


def revoke_google_grants(db: Session, user_id: UUID) -> None:
    """Revoke the user's Gmail + Calendar grants at Google before their token rows
    are deleted. Best-effort; mirrors the connectors' own disconnect/revoke paths."""
    google = db.query(GoogleAccount).filter(GoogleAccount.user_id == user_id).first()
    if google is not None:
        _revoke_one(google.refresh_token, "gmail", user_id)
    calendar = db.query(CalendarAccount).filter(CalendarAccount.user_id == user_id).first()
    if calendar is not None:
        _revoke_one(calendar.refresh_token, "calendar", user_id)


def delete_user_storage_objects(user_id: UUID) -> int:
    """Erase every Storage object the user owns (all under the ``{user_id}/`` key
    prefix in the images bucket). Best-effort; returns the count deleted. If Storage
    is not configured (local dev/tests), returns 0 without raising."""
    try:
        from app.utils.supabase_storage import SupabaseStorageClient

        client = SupabaseStorageClient.from_env()
    except Exception:  # noqa: BLE001 — storage unconfigured (dev/tests) or unavailable
        logger.info("Account-deletion: storage unavailable, skipping object sweep for user %s", user_id)
        return 0
    return client.delete_prefix(f"{user_id}/")


def delete_user_db_rows(db: Session, user_id: UUID) -> Dict[str, int]:
    """Erase every DB row the user owns, in ONE transaction (all-or-nothing).

    Explicit per-table deletes in FK-safe order, then the ``users`` row itself.
    Returns a per-table deleted-row count for logging (counts only, never content).
    Idempotent: a second call deletes 0 rows and still commits cleanly.
    """
    counts: Dict[str, int] = {}
    try:
        # item_images has no user_id — target it via its parent clothing_items.
        # synchronize_session=False: bulk DELETE, no active identity map to reconcile
        # (and the subquery form cannot be evaluated in-Python).
        img_stmt = (
            delete(ItemImage)
            .where(
                ItemImage.clothing_item_id.in_(
                    select(ClothingItem.id).where(ClothingItem.user_id == user_id)
                )
            )
            .execution_options(synchronize_session=False)
        )
        counts["item_images"] = db.execute(img_stmt).rowcount or 0

        for model in _USER_TABLE_DELETE_ORDER:
            stmt = (
                delete(model)
                .where(model.user_id == user_id)
                .execution_options(synchronize_session=False)
            )
            counts[model.__tablename__] = db.execute(stmt).rowcount or 0

        users_stmt = (
            delete(User).where(User.id == user_id).execution_options(synchronize_session=False)
        )
        counts["users"] = db.execute(users_stmt).rowcount or 0
        db.commit()
    except Exception:
        db.rollback()
        raise
    return counts


def delete_auth_identity(user_id: UUID) -> bool:
    """Delete the Supabase Auth (auth.users) identity via the GoTrue Admin API.

    This kills the user's sessions/refresh tokens server-side so the login cannot
    be reused, and (on Postgres) cascades any remaining auth.* rows. Best-effort and
    idempotent: a 404 (already deleted) counts as success. Returns True when the
    identity is known-gone, False when we could not confirm it (e.g. Admin API not
    configured in local dev — there is no auth.users row there to begin with).
    """
    base = settings.supabase_base_url
    key = settings.SUPABASE_SERVICE_ROLE_KEY
    if not base or not key:
        logger.info("Account-deletion: GoTrue admin not configured; skipping identity delete for %s", user_id)
        return False
    url = f"{base}/auth/v1/admin/users/{user_id}"
    try:
        resp = httpx.delete(
            url,
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=10.0,
        )
        if resp.status_code in (200, 204, 404):
            return True
        logger.error("Account-deletion: GoTrue admin delete returned %s for user %s", resp.status_code, user_id)
        return False
    except Exception:  # noqa: BLE001
        logger.error("Account-deletion: GoTrue admin delete call failed for user %s", user_id)
        return False


def delete_account(db: Session, user_id: UUID) -> Dict[str, Any]:
    """Fully erase a user's account. Orchestrates revoke → storage → DB → identity.

    Steps 1, 2 and 4 are best-effort + idempotent; step 3 (DB erasure) is the one
    that MUST succeed and is transactional. Logs user_id + step only, never content.
    """
    logger.info("Account-deletion START user=%s", user_id)

    revoke_google_grants(db, user_id)
    logger.info("Account-deletion step=revoke_google done user=%s", user_id)

    storage_deleted = delete_user_storage_objects(user_id)
    logger.info("Account-deletion step=storage done user=%s objects=%d", user_id, storage_deleted)

    counts = delete_user_db_rows(db, user_id)
    logger.info("Account-deletion step=db_erase done user=%s rows=%d", user_id, sum(counts.values()))

    identity_deleted = delete_auth_identity(user_id)
    logger.info("Account-deletion step=identity done user=%s confirmed=%s", user_id, identity_deleted)

    logger.info("Account-deletion COMPLETE user=%s", user_id)
    return {
        "deleted": True,
        "storage_objects_deleted": storage_deleted,
        "db_rows_deleted": sum(counts.values()),
        "identity_deleted": identity_deleted,
    }
