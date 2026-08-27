"""Playback endpoints (M11; automatic transitions at M13).

Host-only controls that drive the playback state machine:

- ``POST /play/start``    manually start the front of the queue (→ ``SINGING``)
- ``POST /play/end``      the host device reports the video ended naturally (M13:
                          → ``COMPLETED``, then cooldown → countdown → auto-start)
- ``POST /play/skip``     move the current singer to the end of the round (D20; excluded only when they are the only one left)
- ``POST /play/finish``   current singer → ``COMPLETED``, then the countdown (D20)
- ``POST /play/advance``  progress an automatic transition whose phase deadline
                          passed (M13: COOLDOWN → COUNTDOWN → auto-start)
- ``POST /play/pause``    hold automatic progression (``ACTIVE -> PAUSED``)
- ``POST /play/resume``   resume progression (``PAUSED -> ACTIVE``)

Every endpoint returns the authoritative queue snapshot (which carries the
stored ``playback_state``, the transition deadline, and the remaining seconds),
and the routes broadcast the matching realtime events.

Endpoint function names are intentionally distinct from any dependency (D30).
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_host
from app.core.database import get_session
from app.domain.playback import PlaybackState
from app.models.host import Host
from app.realtime.hub import realtime_hub
from app.schemas.queue import QueueSnapshotResponse
from app.schemas.realtime import (
    NextSingerNotifiedEvent,
    QueueUpdatedEvent,
    SessionUpdatedEvent,
    SingerFinishedEvent,
    SingerSkippedEvent,
    SingerStartedEvent,
)
from app.domain.queue_entry import QueueEntryStatus
from app.services.playback import (
    AlreadyPlayingError,
    NoTransitionError,
    NothingPlayingError,
    NothingToPlayError,
    SessionEndedError,
    TransitionNotReadyError,
    playback_service,
)
from app.services.queue import queue_service
from app.services.session import (
    InvalidSessionTransitionError,
    SessionNotFoundError,
    session_service,
)

router = APIRouter(prefix="/api/v1/sessions/{session_id}/play", tags=["playback"])


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="session not found"
    )


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


async def _notify_next_singer(
    session_id: uuid.UUID,
    snapshot: QueueSnapshotResponse,
    phase: Literal["next", "countdown"],
) -> None:
    """Broadcast the in-app ``NextSingerNotified`` event (M15).

    Targets the front ``NEXT`` entry of the snapshot; when no entry is ``NEXT``
    (e.g. the queue is exhausted) nothing is broadcast.
    """
    next_entry = next(
        (e for e in snapshot.queue if e.status is QueueEntryStatus.NEXT), None
    )
    if next_entry is None:
        return
    await realtime_hub.broadcast(
        session_id,
        NextSingerNotifiedEvent(
            session_id=session_id,
            entry_id=next_entry.id,
            participant_name=next_entry.participant_name,
            title=next_entry.title,
            channel=next_entry.channel,
            phase=phase,
        ),
    )


@router.post("/start", response_model=QueueSnapshotResponse)
async def start_playback(
    session_id: uuid.UUID,
    current_host: Annotated[Host, Depends(get_current_host)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QueueSnapshotResponse:
    """Start playing the front of the active queue (→ ``SINGING``, M11)."""
    try:
        entry = await playback_service.start(session, current_host.id, session_id)
    except SessionNotFoundError as exc:
        raise _not_found() from exc
    except (NothingToPlayError, AlreadyPlayingError, SessionEndedError) as exc:
        raise _conflict(str(exc)) from exc
    snapshot = await queue_service.snapshot(session, session_id)
    await realtime_hub.broadcast(
        session_id,
        SingerStartedEvent(
            session_id=session_id,
            entry_id=entry.id,
            participant_name=entry.participant.nickname,
            title=entry.youtube_video.title,
        ),
    )
    await realtime_hub.broadcast(
        session_id, QueueUpdatedEvent(session_id=session_id, snapshot=snapshot)
    )
    return snapshot


@router.post("/end", response_model=QueueSnapshotResponse)
async def end_playback(
    session_id: uuid.UUID,
    current_host: Annotated[Host, Depends(get_current_host)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QueueSnapshotResponse:
    """The host device reports the current video ended naturally (M13).

    The entry becomes ``COMPLETED`` and the automatic transition begins with
    the post-song cooldown.
    """
    try:
        entry = await playback_service.end(session, current_host.id, session_id)
    except SessionNotFoundError as exc:
        raise _not_found() from exc
    except (NothingPlayingError, SessionEndedError) as exc:
        raise _conflict(str(exc)) from exc
    snapshot = await queue_service.snapshot(session, session_id)
    await realtime_hub.broadcast(
        session_id,
        SingerFinishedEvent(session_id=session_id, entry_id=entry.id),
    )
    await realtime_hub.broadcast(
        session_id, QueueUpdatedEvent(session_id=session_id, snapshot=snapshot)
    )
    # M15: the next singer is promoted to NEXT on a natural end; if the cooldown
    # is 0 the countdown starts immediately, so notify both phases.
    await _notify_next_singer(session_id, snapshot, "next")
    if snapshot.playback_state is PlaybackState.COUNTDOWN:
        await _notify_next_singer(session_id, snapshot, "countdown")
    return snapshot


@router.post("/skip", response_model=QueueSnapshotResponse)
async def skip_playback(
    session_id: uuid.UUID,
    current_host: Annotated[Host, Depends(get_current_host)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QueueSnapshotResponse:
    """Skip the current singer (→ ``SKIPPED``) and begin the countdown (D20/M13)."""
    try:
        entry = await playback_service.skip(session, current_host.id, session_id)
    except SessionNotFoundError as exc:
        raise _not_found() from exc
    except (NothingPlayingError, SessionEndedError) as exc:
        raise _conflict(str(exc)) from exc
    snapshot = await queue_service.snapshot(session, session_id)
    await realtime_hub.broadcast(
        session_id,
        SingerSkippedEvent(session_id=session_id, entry_id=entry.id),
    )
    await realtime_hub.broadcast(
        session_id, QueueUpdatedEvent(session_id=session_id, snapshot=snapshot)
    )
    # M15: a skip promotes the next singer to NEXT and begins the countdown
    # immediately (no cooldown), so notify both phases.
    await _notify_next_singer(session_id, snapshot, "next")
    await _notify_next_singer(session_id, snapshot, "countdown")
    return snapshot


@router.post("/finish", response_model=QueueSnapshotResponse)
async def finish_playback(
    session_id: uuid.UUID,
    current_host: Annotated[Host, Depends(get_current_host)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QueueSnapshotResponse:
    """Finish the current singer (→ ``COMPLETED``) and begin the countdown (D20/M13)."""
    try:
        entry = await playback_service.finish(session, current_host.id, session_id)
    except SessionNotFoundError as exc:
        raise _not_found() from exc
    except (NothingPlayingError, SessionEndedError) as exc:
        raise _conflict(str(exc)) from exc
    snapshot = await queue_service.snapshot(session, session_id)
    await realtime_hub.broadcast(
        session_id,
        SingerFinishedEvent(session_id=session_id, entry_id=entry.id),
    )
    await realtime_hub.broadcast(
        session_id, QueueUpdatedEvent(session_id=session_id, snapshot=snapshot)
    )
    # M15: a manual finish promotes the next singer to NEXT and begins the
    # countdown immediately (no cooldown), so notify both phases.
    await _notify_next_singer(session_id, snapshot, "next")
    await _notify_next_singer(session_id, snapshot, "countdown")
    return snapshot


@router.post("/advance", response_model=QueueSnapshotResponse)
async def advance_playback(
    session_id: uuid.UUID,
    current_host: Annotated[Host, Depends(get_current_host)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QueueSnapshotResponse:
    """Progress an automatic transition whose phase deadline passed (M13).

    The host dashboard calls this when its countdown reaches zero; a reopened
    tab with an overdue deadline self-recovers on the next snapshot read.
    """
    try:
        entry = await playback_service.advance(session, current_host.id, session_id)
    except SessionNotFoundError as exc:
        raise _not_found() from exc
    except (TransitionNotReadyError, NoTransitionError, SessionEndedError) as exc:
        raise _conflict(str(exc)) from exc
    snapshot = await queue_service.snapshot(session, session_id)
    if entry is not None:
        # The countdown ended and the next entry auto-started.
        await realtime_hub.broadcast(
            session_id,
            SingerStartedEvent(
                session_id=session_id,
                entry_id=entry.id,
                participant_name=entry.participant.nickname,
                title=entry.youtube_video.title,
            ),
        )
    await realtime_hub.broadcast(
        session_id, QueueUpdatedEvent(session_id=session_id, snapshot=snapshot)
    )
    # M15: entering COUNTDOWN (the cooldown ended) is the countdown-start
    # notification moment for the next singer.
    if snapshot.playback_state is PlaybackState.COUNTDOWN:
        await _notify_next_singer(session_id, snapshot, "countdown")
    return snapshot


@router.post("/pause", response_model=QueueSnapshotResponse)
async def pause_playback(
    session_id: uuid.UUID,
    current_host: Annotated[Host, Depends(get_current_host)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QueueSnapshotResponse:
    """Hold automatic progression (``ACTIVE -> PAUSED``, M11/E22)."""
    try:
        karaoke = await playback_service.pause(session, current_host.id, session_id)
    except SessionNotFoundError as exc:
        raise _not_found() from exc
    except InvalidSessionTransitionError as exc:
        raise _conflict(str(exc)) from exc
    snapshot = await queue_service.snapshot(session, session_id)
    await realtime_hub.broadcast(
        session_id,
        SessionUpdatedEvent(session_id=session_id, status=karaoke.status),
    )
    await realtime_hub.broadcast(
        session_id, QueueUpdatedEvent(session_id=session_id, snapshot=snapshot)
    )
    return snapshot


@router.post("/resume", response_model=QueueSnapshotResponse)
async def resume_playback(
    session_id: uuid.UUID,
    current_host: Annotated[Host, Depends(get_current_host)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QueueSnapshotResponse:
    """Resume progression (``PAUSED -> ACTIVE``, M11)."""
    try:
        karaoke = await playback_service.resume(session, current_host.id, session_id)
    except SessionNotFoundError as exc:
        raise _not_found() from exc
    except InvalidSessionTransitionError as exc:
        raise _conflict(str(exc)) from exc
    snapshot = await queue_service.snapshot(session, session_id)
    await realtime_hub.broadcast(
        session_id,
        SessionUpdatedEvent(session_id=session_id, status=karaoke.status),
    )
    await realtime_hub.broadcast(
        session_id, QueueUpdatedEvent(session_id=session_id, snapshot=snapshot)
    )
    return snapshot
