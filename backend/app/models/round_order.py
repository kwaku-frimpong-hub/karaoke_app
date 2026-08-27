"""SQLAlchemy model for the host's per-round reordered lineup (queue revision).

``round_orders`` records the host's manual participant order for a specific
round. It is per-round: a row only exists for rounds the host reordered, and the
next round (no rows) falls back to join order. ``position`` is 0-based within
the round; the queue sorts by it when the round has a reorder.
"""

import uuid

from sqlalchemy import ForeignKey, Integer, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RoundOrder(Base):
    """A participant's manual position in a reordered round."""

    __tablename__ = "round_orders"
    __table_args__ = (
        UniqueConstraint("round_id", "position", name="uq_round_orders_position"),
        UniqueConstraint(
            "round_id", "participant_id", name="uq_round_orders_participant"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("rounds.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    participant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("participants.id", ondelete="CASCADE"),
        nullable=False,
    )
