"""Tests for the database layer: engine, sessions, and readiness probe."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import check_database_connection, get_session


async def test_check_database_connection(session: AsyncSession) -> None:
    """The readiness probe succeeds against a live session."""
    await check_database_connection(session)


async def test_session_executes_queries(session: AsyncSession) -> None:
    """A session from the factory can run real queries."""
    result = await session.execute(text("SELECT 42 AS answer"))
    assert result.scalar_one() == 42


async def test_get_session_yields_exactly_one_usable_session() -> None:
    """The DI dependency yields exactly one session, usable for queries.

    The dependency wraps the session in ``async with SessionFactory()``, so it
    closes the session when the generator finishes; that lifecycle is provided
    by the context manager rather than asserted via introspection (SQLAlchemy's
    ``is_active`` is not a closed-state signal).
    """
    yielded_sessions: list[AsyncSession] = []

    async for yielded in get_session():
        assert isinstance(yielded, AsyncSession)
        await yielded.execute(text("SELECT 1"))
        yielded_sessions.append(yielded)

    assert len(yielded_sessions) == 1
