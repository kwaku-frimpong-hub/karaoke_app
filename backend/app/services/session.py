"""Karaoke session use-cases (M4).

The service enforces ownership (a session belongs to exactly one host) and the
``SessionStatus`` state machine before touching persistence. Persistence goes
through the database session directly, matching the M3 ``HostAuthService``
pattern; a repository layer is deferred until persistence is actually shared
between services (see docs/DEV_BRAIN.md M3 implementation notes).
"""

import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.playback import PlaybackState
from app.domain.session import SessionStatus
from app.models.round import Round
from app.models.session import Session
#: Join-code alphabet: uppercase and unambiguous (no 0/O, 1/I).
_JOIN_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_JOIN_CODE_LENGTH = 6
#: Bounded retries on the (astronomically unlikely) join-code collision.
_JOIN_CODE_ATTEMPTS = 10


class SessionNotFoundError(Exception):
    """Raised when a session does not exist or is not owned by the host."""


class InvalidSessionTransitionError(Exception):
    """Raised when a requested session-state transition is not allowed."""


def _default_session_name() -> str:
    """Return the default session name, e.g. ``Friday Karaoke - 2026-08-14``.

    Uses the server's local date: the school deployment runs the server in the
    school's timezone, so ``datetime.now().date()`` reflects the actual night.
    """
    return f"Friday Karaoke - {datetime.now().date().isoformat()}"


def _normalize_session_name(name: str | None) -> str:
    """Trim ``name``; fall back to the default name when blank."""
    if name is not None:
        trimmed = name.strip()
        if trimmed:
            return trimmed
    return _default_session_name()


async def _generate_join_code(session: AsyncSession) -> str:
    """Generate an unused join code, retrying on the rare collision.

    The pre-check relies on the ``sessions.join_code`` unique index as a final
    backstop; with 32^6 combinations collisions are effectively impossible for
    a school night's session count.
    """
    for _ in range(_JOIN_CODE_ATTEMPTS):
        code = "".join(
            secrets.choice(_JOIN_CODE_ALPHABET) for _ in range(_JOIN_CODE_LENGTH)
        )
        existing = await session.scalar(
            select(Session.id).where(Session.join_code == code)
        )
        if existing is None:
            return code
    raise RuntimeError("could not generate a unique join code")


class SessionService:
    """Application service for host-owned karaoke sessions."""

    async def create(
        self,
        session: AsyncSession,
        host_id: uuid.UUID,
        name: str | None,
        cooldown_seconds: int | None = None,
        countdown_seconds: int | None = None,
    ) -> Session:
        """Create a session in ``CREATED`` state with round 1, and return it.

        ``cooldown_seconds``/``countdown_seconds`` default from settings
        (M13, PRODUCT_SPEC §10).
        """
        settings = get_settings()
        karaoke = Session(
            host_id=host_id,
            name=_normalize_session_name(name),
            join_code=await _generate_join_code(session),
            status=SessionStatus.CREATED,
            playback_state=PlaybackState.IDLE,
            cooldown_seconds=(
                cooldown_seconds
                if cooldown_seconds is not None
                else settings.post_song_cooldown_seconds
            ),
            countdown_seconds=(
                countdown_seconds
                if countdown_seconds is not None
                else settings.next_singer_countdown_seconds
            ),
        )
        session.add(karaoke)
        await session.flush()  # populate karaoke.id for the round FK
        session.add(Round(session_id=karaoke.id, number=1))
        await session.commit()
        await session.refresh(karaoke)
        return karaoke

    async def get_by_id(
        self, session: AsyncSession, session_id: uuid.UUID
    ) -> Session:
        """Return a session by id regardless of host (used by public flows).

        Raises ``SessionNotFoundError`` when the session does not exist.
        """
        karaoke = await session.scalar(
            select(Session).where(Session.id == session_id)
        )
        if karaoke is None:
            raise SessionNotFoundError(session_id)
        return karaoke

    async def get_for_host(
        self, session: AsyncSession, host_id: uuid.UUID, session_id: uuid.UUID
    ) -> Session:
        """Return the host's session by id.

        Raises ``SessionNotFoundError`` when the session does not exist or
        belongs to another host (indistinguishable on purpose: cross-host
        access must not leak that a session exists).
        """
        karaoke = await session.scalar(
            select(Session).where(
                Session.id == session_id, Session.host_id == host_id
            )
        )
        if karaoke is None:
            raise SessionNotFoundError(session_id)
        return karaoke

    async def list_for_host(
        self, session: AsyncSession, host_id: uuid.UUID
    ) -> list[Session]:
        """Return the host's sessions, newest first.

        Used by the host dashboard home screen (M9): the host logs in, sees
        their sessions, and picks one to run (E11 re-sync after reopening the
        dashboard). Ordering is ``created_at`` desc, ``id`` desc for a stable
        deterministic sort (ties are vanishingly rare and arbitrary).
        """
        result = await session.scalars(
            select(Session)
            .where(Session.host_id == host_id)
            .order_by(Session.created_at.desc(), Session.id.desc())
        )
        return list(result)

    async def start(
        self, session: AsyncSession, host_id: uuid.UUID, session_id: uuid.UUID
    ) -> Session:
        """Transition a session ``CREATED -> ACTIVE`` and stamp ``started_at``."""
        karaoke = await self.get_for_host(session, host_id, session_id)
        if not karaoke.status.can_transition_to(SessionStatus.ACTIVE):
            raise InvalidSessionTransitionError(
                f"session {session_id} cannot start from state "
                f"{karaoke.status.value}"
            )
        karaoke.status = SessionStatus.ACTIVE
        karaoke.started_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(karaoke)
        return karaoke

    async def pause(
        self, session: AsyncSession, host_id: uuid.UUID, session_id: uuid.UUID
    ) -> Session:
        """Transition a session ``ACTIVE -> PAUSED`` (host, M11).

        Holds automatic progression after the current song (E22); manual host
        actions still work while paused.
        """
        karaoke = await self.get_for_host(session, host_id, session_id)
        if not karaoke.status.can_transition_to(SessionStatus.PAUSED):
            raise InvalidSessionTransitionError(
                f"session {session_id} cannot be paused from state "
                f"{karaoke.status.value}"
            )
        karaoke.status = SessionStatus.PAUSED
        await session.commit()
        await session.refresh(karaoke)
        return karaoke

    async def resume(
        self, session: AsyncSession, host_id: uuid.UUID, session_id: uuid.UUID
    ) -> Session:
        """Transition a session ``PAUSED -> ACTIVE`` (host, M11)."""
        karaoke = await self.get_for_host(session, host_id, session_id)
        if not karaoke.status.can_transition_to(SessionStatus.ACTIVE):
            raise InvalidSessionTransitionError(
                f"session {session_id} cannot be resumed from state "
                f"{karaoke.status.value}"
            )
        karaoke.status = SessionStatus.ACTIVE
        await session.commit()
        await session.refresh(karaoke)
        return karaoke

    async def end(
        self, session: AsyncSession, host_id: uuid.UUID, session_id: uuid.UUID
    ) -> Session:
        """Transition a session to ``ENDED`` and stamp ``ended_at``.

        Allowed from any non-terminal state (PRODUCT_SPEC §3).
        """
        karaoke = await self.get_for_host(session, host_id, session_id)
        if not karaoke.status.can_transition_to(SessionStatus.ENDED):
            raise InvalidSessionTransitionError(
                f"session {session_id} is already ended"
            )
        karaoke.status = SessionStatus.ENDED
        karaoke.ended_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(karaoke)
        return karaoke


session_service = SessionService()
