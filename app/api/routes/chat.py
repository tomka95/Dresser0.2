"""POST /chat — the stylist SSE endpoint (Wave S2 scope D) + history reads.

REQUEST LIFECYCLE
  1. get_current_user resolves the JWT — the ONLY source of user identity.
  2. Payload guards: Content-Length ceiling, message-length cap, attachment
     count/type caps; images pass validate_and_sanitize (magic-byte sniff,
     bomb/dimension guards, EXIF strip) before anything else sees them.
  3. Abuse controls, in cost order (cheapest refusal first): fixed-window rate
     limit -> daily free-tier quota -> per-user concurrency slot. All three are
     SHARED cross-worker state in Postgres (see stylist/limits.py). 429 with a
     machine-readable code.
  4. The agent turn runs in a worker thread; a thread-safe asyncio bridge
     forwards events into the SSE response:
        event: meta | token | tool | outfit | done | error
     with a keepalive comment every 15s so proxies don't drop the stream.
  5. Usage/cost is rolled into chat_usage AFTER the turn (owner connection —
     quota bookkeeping is server state, not user data).

The generator never raises into starlette: every failure becomes a terminal
`error` event with a stable code the frontend maps to a friendly message.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.dependencies import get_current_user, get_db
from app.models import User
from app.services.stylist.agent import TurnRequest, run_stylist_turn
from app.services.stylist.limits import (
    ChatLimitExceeded,
    check_quota,
    check_rate_limit,
    record_turn_usage,
    stream_slot,
)
from app.services.stylist.persistence import list_conversations, recent_messages
from app.services.stylist.rls import RlsSetupError, rls_scoped_session
from app.services.stylist.tools import ImageAttachment
from app.utils.image_validation import ImageValidationError, validate_and_sanitize

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

_KEEPALIVE_SECONDS = 15.0
_STREAM_DONE = object()


# ---------------------------------------------------------------------------
# Request schema (sizes enforced by pydantic; body ceiling checked separately)
# ---------------------------------------------------------------------------
class ImageAttachmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["image"]
    # ~5MB binary -> ~6.7MB base64; the whole-body ceiling caps the total.
    dataBase64: str = Field(..., min_length=8, max_length=7_000_000)
    mimeType: str = Field(..., max_length=40)


class ClosetItemAttachmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["closet_item"]
    itemId: str = Field(..., max_length=40)


class ChatRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(..., min_length=1, max_length=settings.CHAT_MAX_MESSAGE_CHARS)
    conversationId: Optional[str] = Field(None, max_length=40)
    attachments: List[Union[ImageAttachmentIn, ClosetItemAttachmentIn]] = Field(
        default_factory=list, max_length=settings.CHAT_MAX_ATTACHMENTS
    )


def _sse(event: str, payload: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


def _parse_uuid(value: Optional[str], *, field: str) -> Optional[UUID]:
    if value is None:
        return None
    try:
        return UUID(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail=f"{field} is not a valid id")


async def _decode_attachments(
    body: ChatRequestIn,
) -> Tuple[List[ImageAttachment], List[UUID]]:
    """Base64-decode + sanitize images (threadpool: CPU-bound), collect item ids."""
    images: List[ImageAttachment] = []
    item_ids: List[UUID] = []
    for att in body.attachments:
        if isinstance(att, ClosetItemAttachmentIn):
            parsed = _parse_uuid(att.itemId, field="attachments[].itemId")
            if parsed is not None:
                item_ids.append(parsed)
            continue
        try:
            raw = base64.b64decode(att.dataBase64, validate=True)
        except Exception:
            raise HTTPException(status_code=422, detail="attachment is not valid base64")
        try:
            sanitized = await run_in_threadpool(validate_and_sanitize, raw)
        except ImageValidationError as exc:
            message = str(exc)
            status = 413 if "exceeds" in message else 422
            raise HTTPException(status_code=status, detail=message)
        images.append(
            ImageAttachment(data=sanitized.data, mime_type=sanitized.content_type)
        )
    return images, item_ids


@router.post("")
async def post_chat(
    request: Request,
    body: ChatRequestIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    # Whole-body ceiling (cheap reject before any decode work).
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.CHAT_MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="request body too large")

    conversation_id = _parse_uuid(body.conversationId, field="conversationId")
    images, attached_item_ids = await _decode_attachments(body)

    # Shared abuse controls (429 before any model spend).
    try:
        check_rate_limit(db, current_user.id)
        check_quota(db, current_user.id)
    except ChatLimitExceeded as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(status_code=429, detail={"code": exc.code, "message": str(exc)},
                            headers=headers)
    finally:
        # Release the request-scoped connection now — the SSE stream below can
        # run for a minute+ and must not pin a pooled connection it never uses
        # (the agent opens its own RLS-scoped connection).
        db.close()

    turn = TurnRequest(
        user_id=current_user.id,
        message=body.message,
        conversation_id=conversation_id,
        images=images,
        attached_item_ids=attached_item_ids,
    )
    user_id = current_user.id

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: str, payload: Dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (event, payload))

    def worker() -> None:
        """Holds the concurrency slot for the full turn; every outcome becomes
        a queue item — the generator below is the only writer to the socket."""
        try:
            with stream_slot(user_id):
                result = run_stylist_turn(turn, emit)
            emit("done", {
                "conversationId": str(result.conversation_id),
                "messageId": str(result.message_id),
                "inputTokens": result.input_tokens,
                "outputTokens": result.output_tokens,
                "costUsd": round(result.cost_usd, 6),
                "model": result.model,
            })
            # Quota bookkeeping on a fresh owner session (thread-local).
            from app.db import SessionLocal

            usage_db = SessionLocal()
            try:
                record_turn_usage(
                    usage_db, user_id,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cost_usd=result.cost_usd,
                )
            finally:
                usage_db.close()
        except ChatLimitExceeded as exc:
            emit("error", {"code": exc.code, "message": str(exc)})
        except RlsSetupError as exc:
            logger.error("chat turn RLS setup failed: %s", exc)
            emit("error", {"code": "server_error",
                           "message": "The stylist is unavailable right now."})
        except Exception as exc:
            logger.error("chat turn failed for user %s: %s", user_id,
                         type(exc).__name__, exc_info=True)
            emit("error", {"code": "turn_failed",
                           "message": "Something went wrong mid-reply. Try again."})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _STREAM_DONE)

    async def event_stream():
        task = loop.run_in_executor(None, worker)
        deadline = loop.time() + settings.CHAT_TURN_TIMEOUT_SECONDS
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    yield _sse("error", {"code": "timeout",
                                         "message": "The stylist took too long. Try again."})
                    break
                try:
                    item = await asyncio.wait_for(
                        queue.get(), timeout=min(_KEEPALIVE_SECONDS, remaining)
                    )
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if item is _STREAM_DONE:
                    break
                event, payload = item
                yield _sse(event, payload)
                if event in ("done", "error"):
                    # Drain the sentinel then stop.
                    continue
        finally:
            # The worker owns its own cleanup (slot release, sessions); we just
            # stop reading. Cancellation of a threadpool task is cooperative.
            task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# History reads (FE reload path). RLS-scoped like every other chat DB touch.
# ---------------------------------------------------------------------------
@router.get("/conversations")
def get_conversations(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    with rls_scoped_session(current_user.id) as db:
        rows = list_conversations(db, current_user.id)
        return {
            "conversations": [
                {
                    "id": str(c.id),
                    "title": c.title,
                    "updatedAt": c.updated_at.isoformat() if c.updated_at else None,
                }
                for c in rows
            ]
        }


@router.get("/conversations/{conversation_id}/messages")
def get_conversation_messages(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    with rls_scoped_session(current_user.id) as db:
        rows = recent_messages(db, current_user.id, conversation_id, limit=50)
        return {
            "messages": [
                {
                    "id": str(m.id),
                    "role": m.role,
                    "content": m.content,
                    "outfit": m.outfit_json,
                    "createdAt": m.created_at.isoformat() if m.created_at else None,
                }
                for m in rows
                if m.role in ("user", "assistant")
            ]
        }
