"""RLS-enforced database access for the stylist agent (locked decision 1).

THE PROBLEM: the backend connects to Postgres as a privileged role that BYPASSES
row-level security — today, cross-tenant isolation rests entirely on app-level
``WHERE user_id = :uid`` filters. One forgotten filter in one tool and the agent
could read another user's wardrobe.

THE MECHANISM: every agent turn runs its DB work inside ONE transaction on a
dedicated connection that first executes::

    SET LOCAL role authenticated;
    SELECT set_config('request.jwt.claims',
                      '{"sub": "<jwt-user-id>", "role": "authenticated"}', true);

``SET LOCAL role`` drops the connection to the Supabase ``authenticated`` role for
the remainder of the transaction — a role that is subject to RLS on every table.
``request.jwt.claims`` is the exact GUC Supabase's ``auth.uid()`` reads, so every
0018/0020 policy (``auth.uid() = user_id``) now evaluates against the JWT subject
the SERVER derived — never anything the model or client supplied. Both settings
are transaction-local (the third ``set_config`` argument = true): when the
transaction ends the connection reverts to the owner role automatically, so a
pooled connection can never leak the impersonation into another request.

Result: even if a tool forgot its WHERE clause entirely, Postgres itself returns
zero foreign rows. App-level filters are kept everywhere regardless
(defense-in-depth, and they are what the SQLite dev/test path relies on).

FAIL-LOUD: on Postgres, if the role switch fails (role missing / not granted),
the turn raises ``RlsSetupError`` -> HTTP 503. It never silently degrades to the
RLS-bypassing owner connection. ``CHAT_RLS_ENFORCED=false`` is the explicit,
logged opt-out for non-Supabase local Postgres.

SQLite (dev/test) has no roles or RLS; the scope helper degrades to a plain
session there and the app-level filters are the (tested) guard.
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Iterator
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import engine

logger = logging.getLogger(__name__)


class RlsSetupError(RuntimeError):
    """Raised when the RLS-enforced connection cannot be established on Postgres.

    Deliberately fatal for the turn: the agent must never fall back to the
    RLS-bypassing owner connection silently.
    """


@contextmanager
def rls_scoped_session(user_id: UUID) -> Iterator[Session]:
    """Yield a Session whose ENTIRE lifetime runs as the RLS-enforced
    ``authenticated`` role with ``request.jwt.claims.sub = user_id``.

    One transaction per turn: commit on clean exit, rollback on error. The role
    and claims are transaction-local, so the underlying pooled connection is
    clean when returned.
    """
    if engine.dialect.name != "postgresql":
        # SQLite dev/test: no roles/RLS — app-level WHERE user_id is the guard.
        session = Session(bind=engine)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        return

    if not settings.CHAT_RLS_ENFORCED:
        logger.warning(
            "CHAT_RLS_ENFORCED=false: stylist tools running WITHOUT the RLS "
            "backstop (app-level WHERE user_id only). Dev-only posture."
        )
        session = Session(bind=engine)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        return

    connection = engine.connect()
    try:
        transaction = connection.begin()
        try:
            claims = json.dumps({"sub": str(user_id), "role": "authenticated"})
            connection.execute(text("SET LOCAL role authenticated"))
            connection.execute(
                text("SELECT set_config('request.jwt.claims', :claims, true)"),
                {"claims": claims},
            )
        except Exception as exc:
            transaction.rollback()
            raise RlsSetupError(
                "Could not establish the RLS-enforced agent connection "
                f"({type(exc).__name__}). Refusing to run stylist tools on the "
                "RLS-bypassing owner connection. Ensure the 'authenticated' role "
                "exists and is grantable, or set CHAT_RLS_ENFORCED=false for a "
                "non-Supabase local database."
            ) from exc

        session = Session(bind=connection)
        try:
            yield session
            session.flush()
            transaction.commit()
        except Exception:
            transaction.rollback()
            raise
        finally:
            session.close()
    finally:
        connection.close()
