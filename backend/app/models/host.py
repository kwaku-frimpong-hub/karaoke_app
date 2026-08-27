"""SQLAlchemy model for a host account (M3).

A host is an authenticated account that can create and manage sessions
(``docs/DOMAIN_MODEL.md``). Emails are normalized to lowercase by the auth
service before persistence, so the unique constraint provides
case-insensitive uniqueness on every supported dialect.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.host_auth_token import HostAuthToken


class Host(Base):
    """A registered host account."""

    __tablename__ = "hosts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(
        String(320), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    auth_tokens: Mapped[list["HostAuthToken"]] = relationship(
        back_populates="host", cascade="all, delete-orphan"
    )
