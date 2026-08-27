"""SQLAlchemy model for a queue entry (M7).

A QueueEntry is one participant's song in a round. Ordering is derived from
``created_at`` (decision D8): positions are computed when rendered, never
stored. Status is a non-native enum (VARCHAR), portable across SQLite tests
and PostgreSQL (D22).
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.queue_entry import QueueEntryStatus
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.participant import Participant
    from app.models.round import Round
    from app.models.youtube_video import YouTubeVideo


class QueueEntry(Base):
    """A participant's song waiting in (or processed from) the queue."""

    __tablename__ = "queue_entries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    round_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("rounds.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("participants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    youtube_video_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("youtube_videos.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[QueueEntryStatus] = mapped_column(
        Enum(QueueEntryStatus, native_enum=False, length=32),
        default=QueueEntryStatus.WAITING,
        server_default="WAITING",
        nullable=False,
    )
    #: How many times this entry was skipped-and-moved to the end of its round
    #: (queue revision): it sorts after entries that were never skipped.
    skip_count: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    #: Creation order determines queue position (D8). A Python-side default
    #: with microsecond precision preserves insertion order on SQLite (whose
    #: ``CURRENT_TIMESTAMP`` is second-precision); ``id`` is the deterministic
    #: tie-break for same-instant submissions (E19).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Read relationships for building responses (lazy="selectin" avoids N+1
    # when loading a queue snapshot).
    participant: Mapped["Participant"] = relationship(lazy="selectin")
    youtube_video: Mapped["YouTubeVideo"] = relationship(lazy="selectin")
    round: Mapped["Round"] = relationship(lazy="selectin")
