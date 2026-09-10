"""Pydantic schemas for the queue API (M7)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.playback import PlaybackState
from app.domain.queue_entry import QueueEntryStatus
from app.domain.session import SessionStatus

#: Maximum accepted length of a pasted/edited YouTube URL.
MAX_YOUTUBE_URL_LENGTH = 2048


class SongUrlRequest(BaseModel):
    """Request body for submitting a song or editing an entry's URL (M7)."""

    youtube_url: str = Field(max_length=MAX_YOUTUBE_URL_LENGTH)


class QueueEntryResponse(BaseModel):
    """A queue entry with its (computed) position.

    Position is derived from the authoritative creation order (D8) and is
    ``None`` only when it cannot be computed (processed entries).
    """

    id: uuid.UUID
    participant_name: str
    status: QueueEntryStatus
    video_id: str
    youtube_url: str
    title: str
    channel: str
    duration_seconds: int
    thumbnail_url: str
    position: int | None
    created_at: datetime


class SongSubmitResponse(BaseModel):
    """Response for a successful submission (B15/B16)."""

    entry: QueueEntryResponse
    #: True when the same video is already in the queue (never a block, B16).
    duplicate: bool
    notice: str | None


class QueueParticipant(BaseModel):
    """Per-participant queue summary (M16): how many songs remain queued."""

    nickname: str
    remaining_songs: int


class QueueSnapshotResponse(BaseModel):
    """Public, sanitized queue view (no host identity, no participant tokens).

    ``round_number`` is the active round (M10.1, D43): the round currently being
    sung, or the highest round that exists when the queue is empty.
    ``playback_state`` is the stored playback state (M13, D47) — ``PLAYING``
    while an entry is ``SINGING``, ``IDLE`` when idle, and ``COOLDOWN``/
    ``COUNTDOWN`` during an automatic transition. ``transition_until`` is the
    absolute deadline of the current transition phase (None otherwise) and
    ``transition_remaining_seconds`` its remaining time for countdown display;
    ``cooldown_seconds``/``countdown_seconds`` expose the per-session timing
    configuration so clients can render temporary optimistic transition UI while
    awaiting the next authoritative snapshot.
    ``rounds_completed`` and ``participants`` (per-participant remaining-song
    counts) are the M16 round summaries.
    """

    session_id: uuid.UUID
    status: SessionStatus
    round_number: int
    rounds_completed: int
    playback_state: PlaybackState
    transition_until: datetime | None
    transition_remaining_seconds: float | None
    cooldown_seconds: int
    countdown_seconds: int
    participants: list[QueueParticipant]
    queue: list[QueueEntryResponse]
