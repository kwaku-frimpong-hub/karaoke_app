"""SQLAlchemy model for a session-scoped participant (M5).

A participant is an anonymous, session-scoped identity created when someone
joins a session by nickname (``docs/DOMAIN_MODEL.md``). No account exists.
Only the SHA-256 digest of the participant's opaque token is stored (same
pattern as host tokens, D25); the raw token is returned to the client once.

Nickname uniqueness is case-insensitive per session (B14/D16): the display
``nickname`` preserves the case the student typed, while ``nickname_lower``
feeds a portable (session_id, lowercased) unique constraint.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Uuid, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Participant(Base):
    """A session-scoped identity for an anonymous karaoke participant."""

    __tablename__ = "participants"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "nickname_lower",
            name="uq_participants_session_nickname",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    nickname: Mapped[str] = mapped_column(String(20), nullable=False)
    nickname_lower: Mapped[str] = mapped_column(String(20), nullable=False)
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    #: Python-side microsecond default keeps join order deterministic on SQLite
    #: (whose ``CURRENT_TIMESTAMP`` is second-precision); ``id`` is the tie-break.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    #: When the participant last connected to the realtime channel (M16). Set at
    #: join and refreshed on each WebSocket connect; NULL means "never tracked"
    #: (treated as present — never cleaned up).
    last_connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
