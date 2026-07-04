"""Chat persistence (Wave S2 scope B): conversations + messages + retention.

All functions take an explicit ``user_id`` (the JWT subject) and filter on it —
the app-level tenant guard the RLS-scoped session backstops. Nothing here
commits unless stated: the caller owns the transaction (mirrors
events_service/onboarding_service).

RETENTION: conversations carry a rolling ``expires_at`` TTL
(CHAT_RETENTION_DAYS). Every appended message pushes it forward;
:func:`sweep_expired_conversations` deletes the CALLER's expired rows (messages
cascade) and runs opportunistically on conversation access — the same
opportunistic-sweep pattern photo_detect_sessions uses. No cron dependency.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ChatMessage, Conversation

logger = logging.getLogger(__name__)

_TITLE_MAX = 80


def _retention_horizon() -> datetime:
    return datetime.utcnow() + timedelta(days=settings.CHAT_RETENTION_DAYS)


def sweep_expired_conversations(db: Session, user_id: UUID) -> int:
    """Delete the caller's expired conversations (messages cascade). Returns count."""
    now = datetime.utcnow()
    expired = (
        db.query(Conversation)
        .filter(Conversation.user_id == user_id, Conversation.expires_at < now)
        .all()
    )
    for conversation in expired:
        db.delete(conversation)
    if expired:
        logger.info("chat retention: swept %d conversation(s) for user %s",
                    len(expired), user_id)
    return len(expired)


def get_or_create_conversation(
    db: Session, user_id: UUID, conversation_id: Optional[UUID], *, first_message: str = ""
) -> Conversation:
    """Resolve the caller's conversation, or create one titled from the first
    message. A foreign/unknown id gets a FRESH conversation (fail closed —
    never attach to a row the caller doesn't own)."""
    sweep_expired_conversations(db, user_id)
    if conversation_id is not None:
        conversation = (
            db.query(Conversation)
            .filter(Conversation.id == conversation_id,
                    Conversation.user_id == user_id)
            .one_or_none()
        )
        if conversation is not None:
            return conversation
    title = (first_message or "").strip()[:_TITLE_MAX] or None
    conversation = Conversation(user_id=user_id, title=title)
    db.add(conversation)
    db.flush()
    return conversation


def append_message(
    db: Session,
    conversation: Conversation,
    *,
    role: str,
    content: str,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    outfit_json: Optional[Dict[str, Any]] = None,
    model: Optional[str] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
) -> ChatMessage:
    """Append one transcript row and roll the conversation's TTL forward."""
    message = ChatMessage(
        conversation_id=conversation.id,
        user_id=conversation.user_id,
        role=role,
        content=content or "",
        tool_calls=tool_calls,
        outfit_json=outfit_json,
        model=model,
        input_tokens=int(input_tokens or 0),
        output_tokens=int(output_tokens or 0),
        cost_usd=float(cost_usd or 0.0),
    )
    db.add(message)
    conversation.updated_at = datetime.utcnow()
    conversation.expires_at = _retention_horizon()
    db.flush()
    return message


def recent_messages(
    db: Session, user_id: UUID, conversation_id: UUID, *, limit: Optional[int] = None
) -> List[ChatMessage]:
    """The transcript window (oldest-first), tenant-filtered."""
    limit = limit or settings.CHAT_HISTORY_WINDOW
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.conversation_id == conversation_id,
                ChatMessage.user_id == user_id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(rows))


def delete_conversation(db: Session, user_id: UUID, conversation_id: UUID) -> bool:
    """Delete the caller's conversation (messages cascade). Returns True if a row
    was owned + deleted, False otherwise. Tenant-filtered so one user can never
    delete another's thread; the RLS-scoped session backstops it. No commit —
    the caller owns the transaction."""
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user_id)
        .one_or_none()
    )
    if conversation is None:
        return False
    db.delete(conversation)
    db.flush()
    return True


def list_conversations(db: Session, user_id: UUID, *, limit: int = 20) -> List[Conversation]:
    sweep_expired_conversations(db, user_id)
    return (
        db.query(Conversation)
        .filter(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
        .all()
    )
