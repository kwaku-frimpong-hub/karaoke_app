"""Host authentication use-cases (M3).

Coordinates password hashing, token issuance/revocation, and persistence via
the database session. Domain errors are raised as exceptions and translated
to HTTP responses by the API layer.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.config import get_settings
from app.core.security import (
    generate_auth_token,
    hash_auth_token,
    hash_password,
    verify_password,
)
from app.models.host import Host
from app.models.host_auth_token import HostAuthToken


class HostAlreadyExistsError(Exception):
    """Raised when registering an email that already has an account."""


class InvalidCredentialsError(Exception):
    """Raised on login with an unknown email or wrong password."""


def _normalize_email(email: str) -> str:
    """Normalize an email for storage/lookup (lowercase, trimmed).

    Combined with the database unique constraint this gives case-insensitive
    uniqueness for host accounts.
    """
    return email.strip().lower()


def _is_expired(expires_at: datetime) -> bool:
    """Return True if ``expires_at`` is in the past.

    Handles both timezone-aware and naive datetimes because the SQLite test
    dialect returns naive values while PostgreSQL returns aware ones.
    """
    now = datetime.now(timezone.utc)
    if expires_at.tzinfo is None:
        now = now.replace(tzinfo=None)
    return expires_at < now


class HostAuthService:
    """Application service for host registration, login, and logout."""

    def __init__(self) -> None:
        self._token_ttl_days: int = get_settings().auth_token_ttl_days

    async def register(self, session: AsyncSession, email: str, password: str) -> Host:
        """Create a host account and return it.

        Raises ``HostAlreadyExistsError`` if the email is already registered.
        """
        normalized_email = _normalize_email(email)
        existing = await session.scalar(
            select(Host).where(Host.email == normalized_email)
        )
        if existing is not None:
            raise HostAlreadyExistsError(normalized_email)

        host = Host(email=normalized_email, password_hash=hash_password(password))
        session.add(host)
        try:
            await session.commit()
        except IntegrityError as exc:
            # Lost a concurrent registration race to the unique constraint.
            await session.rollback()
            raise HostAlreadyExistsError(normalized_email) from exc
        await session.refresh(host)
        return host

    async def login(self, session: AsyncSession, email: str, password: str) -> tuple[Host, str]:
        """Authenticate a host and issue a new bearer token.

        Returns ``(host, raw_token)``. Raises ``InvalidCredentialsError`` for
        an unknown email or wrong password (same message for both, to avoid
        account enumeration).
        """
        normalized_email = _normalize_email(email)
        host = await session.scalar(select(Host).where(Host.email == normalized_email))
        if host is None or not verify_password(password, host.password_hash):
            raise InvalidCredentialsError()

        raw_token = generate_auth_token()
        token = HostAuthToken(
            host_id=host.id,
            token_hash=hash_auth_token(raw_token),
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=self._token_ttl_days),
        )
        session.add(token)
        await session.commit()
        return host, raw_token

    async def logout(self, session: AsyncSession, raw_token: str) -> None:
        """Revoke a bearer token (idempotent; unknown tokens are a no-op)."""
        await session.execute(
            delete(HostAuthToken).where(
                HostAuthToken.token_hash == hash_auth_token(raw_token)
            )
        )
        await session.commit()

    async def get_host_by_token(self, session: AsyncSession, raw_token: str) -> Host | None:
        """Return the host owning ``raw_token``, or None if unknown/expired."""
        token = await session.scalar(
            select(HostAuthToken)
            .where(HostAuthToken.token_hash == hash_auth_token(raw_token))
            .options(joinedload(HostAuthToken.host))
        )
        if token is None or _is_expired(token.expires_at):
            return None
        return token.host


host_auth_service = HostAuthService()
