"""Typed realtime event payloads (M10; singer events M11; notifications M15).

WebSockets are a delivery mechanism, not the source of truth (decision D5):
the backend broadcasts these events to a session's subscribers after a domain
change, and a reconnecting client must re-fetch authoritative state from the
REST API. Event payloads carry typed fields only — never free-form strings
(API_CONTRACT §8).

Emitted events correspond to domain changes that already exist:
- ``QueueUpdated``       queue mutated (submit, cancel, remove, edit, playback
                         status changes) — the payload is the full authoritative
                         queue snapshot
- ``ParticipantJoined``  a new participant registered in the session
- ``SessionUpdated``     session status changed (started/ended; paused/resumed)
- ``SingerStarted``      the host started an entry (M11)
- ``SingerFinished``     an entry completed (M11)
- ``SingerSkipped``      an entry was skipped (M11)
- ``NextSingerNotified`` the next singer was notified (M15, in-app): phase
                         ``next`` when their entry is promoted to ``NEXT`` and
                         phase ``countdown`` when the countdown transition begins

Web Push (out-of-band notifications) is deferred: M15 is in-app only (see
DECISIONS open question).
"""

import uuid
from typing import Literal, Union

from pydantic import BaseModel

from app.domain.session import SessionStatus
from app.schemas.queue import QueueSnapshotResponse


class QueueUpdatedEvent(BaseModel):
    """Broadcast whenever the session's queue changes.

    ``snapshot`` is the full authoritative ``QueueSnapshotResponse`` so every
    subscriber can render the same state the REST snapshot would return.
    """

    type: str = "QueueUpdated"
    session_id: uuid.UUID
    snapshot: QueueSnapshotResponse


class ParticipantJoinedEvent(BaseModel):
    """Broadcast when a participant registers in the session (M5 join flow)."""

    type: str = "ParticipantJoined"
    session_id: uuid.UUID
    nickname: str


class SessionUpdatedEvent(BaseModel):
    """Broadcast when the session status changes (M4 start/end, M11 pause/resume)."""

    type: str = "SessionUpdated"
    session_id: uuid.UUID
    status: SessionStatus


class SingerStartedEvent(BaseModel):
    """Broadcast when the host starts an entry (promoted to ``SINGING``, M11)."""

    type: str = "SingerStarted"
    session_id: uuid.UUID
    entry_id: uuid.UUID
    participant_name: str
    title: str


class SingerFinishedEvent(BaseModel):
    """Broadcast when the host finishes an entry (``COMPLETED``, M11)."""

    type: str = "SingerFinished"
    session_id: uuid.UUID
    entry_id: uuid.UUID


class SingerSkippedEvent(BaseModel):
    """Broadcast when the host skips an entry (``SKIPPED``, M11)."""

    type: str = "SingerSkipped"
    session_id: uuid.UUID
    entry_id: uuid.UUID


class NextSingerNotifiedEvent(BaseModel):
    """In-app notification for the next singer (M15, PRODUCT_SPEC §11).

    Phase ``next`` fires when the participant's entry is promoted to ``NEXT``
    (the previous song ended); phase ``countdown`` fires when the countdown
    transition begins (~``countdown_seconds`` before their song). Delivered to
    every subscriber; the participant's device filters on ``participant_name``.
    """

    type: str = "NextSingerNotified"
    session_id: uuid.UUID
    entry_id: uuid.UUID
    participant_name: str
    title: str
    channel: str
    phase: Literal["next", "countdown"]


#: The union of events the hub may deliver (typed, discriminated by ``type``).
RealtimeEvent = Union[
    QueueUpdatedEvent,
    ParticipantJoinedEvent,
    SessionUpdatedEvent,
    SingerStartedEvent,
    SingerFinishedEvent,
    SingerSkippedEvent,
    NextSingerNotifiedEvent,
]
