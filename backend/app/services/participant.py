"""Public join use-cases (M5).

Lets a student reach a session by its join code and register a session-scoped
participant identity (nickname + opaque token). No participant account exists
(decision D6). The nickname rules (B14/D16) and the ended-session guard are
enforced here; token hygiene follows D25 (only a SHA-256 digest is stored).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_auth_token, hash_auth_token
from app.domain.queue_entry import QueueEntryStatus
from app.domain.session import SessionStatus
from app.models.participant import Participant
from app.models.queue_entry import QueueEntry
from app.models.session import Session
from app.schemas.participant import MAX_NICKNAME_LENGTH, MIN_NICKNAME_LENGTH
from app.services.session import SessionNotFoundError


class SessionEndedError(Exception):
    """Raised when trying to join a session that is already ended."""


class InvalidNicknameError(Exception):
    """Raised when a nickname violates the B14/D16 rules."""


class NicknameTakenError(Exception):
    """Raised when the nickname is already used in the session (case-insensitive)."""


class ParticipantNotFoundError(Exception):
    """Raised when a participant does not exist in the expected session."""


def normalize_join_code(join_code: str) -> str:
    """Normalize a join code for lookup (codes are uppercase, D27)."""
    return join_code.strip().upper()


def _normalize_nickname(nickname: str) -> str:
    """Trim the nickname; raises ``InvalidNicknameError`` if the result is out
    of the 1-20 character range (B14/D16)."""
    trimmed = nickname.strip()
    if not (MIN_NICKNAME_LENGTH <= len(trimmed) <= MAX_NICKNAME_LENGTH):
        raise InvalidNicknameError(
            f"nickname must be {MIN_NICKNAME_LENGTH}-{MAX_NICKNAME_LENGTH} "
            "characters after trimming"
        )
    return trimmed


class ParticipantService:
    """Application service for the public join flow."""

    async def get_by_token(
        self, session: AsyncSession, raw_token: str
    ) -> Participant | None:
        """Return the participant owning ``raw_token``, or None if unknown.

        Used by the ``get_current_participant`` dependency (M6+).
        """
        return await session.scalar(
            select(Participant).where(
                Participant.token_hash == hash_auth_token(raw_token)
            )
        )

    async def get_session_for_join(
        self, session: AsyncSession, join_code: str
    ) -> Session:
        """Return the session for a join code (public).

        Raises ``SessionNotFoundError`` when the code is unknown.
        """
        karaoke = await session.scalar(
            select(Session).where(
                Session.join_code == normalize_join_code(join_code)
            )
        )
        if karaoke is None:
            raise SessionNotFoundError(join_code)
        return karaoke

    async def register(
        self, session: AsyncSession, join_code: str, nickname: str
    ) -> tuple[Participant, str]:
        """Register a participant in the session and return ``(participant,
        raw_token)``.

        Raises ``SessionNotFoundError`` (unknown code), ``SessionEndedError``
        (ended session), ``InvalidNicknameError`` (bad nickname), or
        ``NicknameTakenError`` (case-insensitive duplicate in the session).
        """
        karaoke = await self.get_session_for_join(session, join_code)
        if karaoke.status is SessionStatus.ENDED:
            raise SessionEndedError(karaoke.id)

        display_nickname = _normalize_nickname(nickname)
        nickname_lower = display_nickname.lower()

        existing = await session.scalar(
            select(Participant.id).where(
                Participant.session_id == karaoke.id,
                Participant.nickname_lower == nickname_lower,
            )
        )
        if existing is not None:
            raise NicknameTakenError(display_nickname)

        raw_token = generate_auth_token()
        participant = Participant(
            session_id=karaoke.id,
            nickname=display_nickname,
            nickname_lower=nickname_lower,
            token_hash=hash_auth_token(raw_token),
            last_connected_at=datetime.now(timezone.utc),
        )
        session.add(participant)
        try:
            await session.commit()
        except IntegrityError as exc:
            # Lost a concurrent registration race to the unique constraint.
            await session.rollback()
            raise NicknameTakenError(display_nickname) from exc
        await session.refresh(participant)
        return participant, raw_token

    async def register_in_session(
        self, session: AsyncSession, session_id: uuid.UUID, nickname: str
    ) -> tuple[Participant, str]:
        """Host-created participant for a known session id.

        Mirrors the public join registration rules: nicknames are normalized and
        unique per session, ended sessions reject new participants, and a token
        hash is still stored even though the host UI does not expose the raw
        token. ``last_connected_at`` stays ``None`` because host-created
        participants have no device/WebSocket presence to refresh; the host
        manages their participation explicitly.
        """
        karaoke = await session.scalar(select(Session).where(Session.id == session_id))
        if karaoke is None:
            raise SessionNotFoundError(session_id)
        if karaoke.status is SessionStatus.ENDED:
            raise SessionEndedError(karaoke.id)

        display_nickname = _normalize_nickname(nickname)
        nickname_lower = display_nickname.lower()

        existing = await session.scalar(
            select(Participant.id).where(
                Participant.session_id == karaoke.id,
                Participant.nickname_lower == nickname_lower,
            )
        )
        if existing is not None:
            raise NicknameTakenError(display_nickname)

        raw_token = generate_auth_token()
        participant = Participant(
            session_id=karaoke.id,
            nickname=display_nickname,
            nickname_lower=nickname_lower,
            token_hash=hash_auth_token(raw_token),
            last_connected_at=None,
        )
        session.add(participant)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise NicknameTakenError(display_nickname) from exc
        await session.refresh(participant)
        return participant, raw_token

    async def get_in_session(
        self, session: AsyncSession, session_id: uuid.UUID, participant_id: uuid.UUID
    ) -> Participant:
        """Return a participant in a session, or raise ``ParticipantNotFoundError``."""
        participant = await session.scalar(
            select(Participant).where(
                Participant.id == participant_id,
                Participant.session_id == session_id,
            )
        )
        if participant is None:
            raise ParticipantNotFoundError(participant_id)
        return participant

    async def leave(self, session: AsyncSession, participant: Participant) -> bool:
        """Delete the participant and all their songs (leave the night early).

        The ``participants`` row is deleted; ``ON DELETE CASCADE`` removes their
        queue entries (every round) and any reorder rows, so they never appear
        in later rounds and their nickname is freed (a rejoin is a fresh
        identity). Returns whether they were the current ``SINGING`` singer so
        the caller can advance playback (E6).
        """
        was_singing = (
            await session.scalar(
                select(QueueEntry.id).where(
                    QueueEntry.participant_id == participant.id,
                    QueueEntry.status == QueueEntryStatus.SINGING,
                )
            )
            is not None
        )
        await session.delete(participant)
        await session.commit()
        return was_singing


participant_service = ParticipantService()
