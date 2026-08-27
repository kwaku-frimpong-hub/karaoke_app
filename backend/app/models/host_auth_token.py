"""SQLAlchemy model for host auth tokens (M3).

One row per issued bearer token. Only the SHA-256 digest of the token is
stored (see ``app.core.security``); the raw token is returned to the client
exactly once. Deleting a row revokes the token (logout).
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.host import Host


class HostAuthToken(Base):
    """An issued (and revocable) bearer token for a host."""

    __tablename__ = "host_auth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    host_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("hosts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    host: Mapped["Host"] = relationship(back_populates="auth_tokens")
