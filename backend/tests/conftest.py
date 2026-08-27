"""Pytest fixtures and environment setup.

The test suite is self-contained: it runs against an in-memory SQLite
database (via ``KARAOKE_DATABASE_URL``) so no PostgreSQL is required. The
environment variables are set before the application is imported so the
cached settings and the global engine pick them up.
"""

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

# The test suite is self-contained: it runs against an in-memory SQLite
# database. These are hard assignments (not setdefault) so that a developer's
# exported KARAOKE_* shell variables or a local backend/.env file cannot leak
# into the test run — real environment variables take precedence over dotenv
# values in pydantic-settings.
os.environ["KARAOKE_ENVIRONMENT"] = "test"
os.environ["KARAOKE_LOG_LEVEL"] = "WARNING"
os.environ["KARAOKE_DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["KARAOKE_DEBUG"] = "false"
# M17: the suite is not coupled to wall-clock rate-limit windows; the limiter
# itself is unit-tested directly and via an explicit 429 test that re-enables it.
os.environ["KARAOKE_RATE_LIMITS_ENABLED"] = "false"

from app.core.database import SessionFactory, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def _create_schema() -> AsyncIterator[None]:
    """Recreate all tables before every test for isolation.

    The test engine uses a single in-memory SQLite database (static pool), so
    dropping and recreating the schema per test keeps tests independent while
    exercising the real ORM models.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
def client() -> TestClient:
    """A TestClient bound to the application with the SQLite engine."""
    return TestClient(app)


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """An async database session against the in-memory SQLite database."""
    async with SessionFactory() as test_session:
        yield test_session
