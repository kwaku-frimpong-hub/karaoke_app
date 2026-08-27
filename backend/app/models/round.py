"""SQLAlchemy model for a karaoke round (M7).

A Session contains one or more numbered rounds (D10). Round 1 is created with
the session; later rounds are created by the round system (M16). Status is
implied by session/queue state and formalized in M16, so the row carries only
timestamps for now.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Uuid, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Round(Base):
    """One pass through the queue within a session."""

    __tablename__ = "rounds"
    __table_args__ = (
        UniqueConstraint("session_id", "number", name="uq_rounds_session_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    number: Mapped[int] = mapped_column(nullable=False)
    #: Python-side default keeps inserts working on a migrated SQLite DB (whose
    #: ``CURRENT_TIMESTAMP``/``now()`` server default differs by dialect).
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
