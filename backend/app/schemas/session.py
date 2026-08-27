"""Pydantic schemas for the session API (M4; transition timings at M13)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.playback import PlaybackState
from app.domain.session import SessionStatus


class SessionCreateRequest(BaseModel):
    """Request body for ``POST /api/v1/sessions``.

    ``name`` is optional; the service falls back to
    ``Friday Karaoke - <server-local date>`` when omitted or blank.
    ``cooldown_seconds``/``countdown_seconds`` override the automatic-transition
    timings (M13, PRODUCT_SPEC §10); defaults come from settings.
    """

    name: str | None = Field(default=None, max_length=100)
    cooldown_seconds: int | None = Field(default=None, ge=0, le=3600)
    countdown_seconds: int | None = Field(default=None, ge=0, le=3600)


class ReorderRequest(BaseModel):
    """Request body for ``PATCH /api/v1/sessions/{id}/order``.

    The desired participant order for the **current round** (host reorder,
    per-round; the next round resets to join order). Nicknames are unique per
    session (B14/D16).
    """

    participant_names: list[str] = Field(min_length=1, max_length=50)


class SessionResponse(BaseModel):
    """Host-facing view of a session."""

    id: uuid.UUID
    name: str
    join_code: str
    join_url: str
    status: SessionStatus
    playback_state: PlaybackState
    cooldown_seconds: int
    countdown_seconds: int
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None


class SessionParticipantSummary(BaseModel):
    """Per-participant round statistics (M16)."""

    nickname: str
    songs_submitted: int
    songs_sung: int
    songs_remaining: int


class SessionSummaryResponse(BaseModel):
    """Host-facing round/session summary (M16, end-of-night wrap-up)."""

    session_id: uuid.UUID
    status: SessionStatus
    active_round: int
    rounds_completed: int
    participants: list[SessionParticipantSummary]
