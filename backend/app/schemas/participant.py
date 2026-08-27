"""Pydantic schemas for the public join flow (M5)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.session import SessionStatus

#: Nickname rules (B14/D16): required, trimmed, 1-20 characters.
MIN_NICKNAME_LENGTH = 1
MAX_NICKNAME_LENGTH = 20


class ParticipantCreateRequest(BaseModel):
    """Request body for ``POST /api/v1/join/{join_code}/participants``."""

    nickname: str = Field(
        min_length=MIN_NICKNAME_LENGTH, max_length=MAX_NICKNAME_LENGTH
    )


class JoinSessionResponse(BaseModel):
    """Public, minimal snapshot of a session for the join screen.

    Deliberately excludes host identity and join-internal fields; enough for a
    student to confirm they reached the right night and to render the
    "session ended" state (E18).
    """

    id: uuid.UUID
    name: str
    status: SessionStatus


class ParticipantResponse(BaseModel):
    """Public view of a registered participant."""

    id: uuid.UUID
    session_id: uuid.UUID
    nickname: str
    created_at: datetime


class ParticipantJoinResponse(BaseModel):
    """Response for a successful join: opaque token + session + participant."""

    token: str
    token_type: Literal["bearer"] = "bearer"
    session: JoinSessionResponse
    participant: ParticipantResponse
