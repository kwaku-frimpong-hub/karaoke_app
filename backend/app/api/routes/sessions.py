"""Karaoke session endpoints (M4).

All session endpoints require a host bearer token (``get_current_host``) and
are scoped to the session's owning host (decision D29). Base path confirmed at
M3 (D26): business endpoints live under ``/api/v1``.

- ``POST /api/v1/sessions``           create a session (host)
- ``GET  /api/v1/sessions``           list the host's sessions, newest first (M9)
- ``GET  /api/v1/sessions/{id}``      get a session (owning host)
- ``POST /api/v1/sessions/{id}/start`` start a session (owning host)
- ``POST /api/v1/sessions/{id}/end``  end a session (owning host)
- ``GET  /api/v1/sessions/{id}/qr``   QR code of the join URL (owning host, M5)
"""

import io
import uuid
from typing import Annotated

import segno
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_current_host,
    get_current_participant,
)
from app.core.config import get_settings
from app.core.database import get_session
from app.models.host import Host
from app.models.participant import Participant
from app.models.session import Session
from app.realtime.hub import realtime_hub
from app.schemas.queue import QueueSnapshotResponse
from app.schemas.realtime import QueueUpdatedEvent, SessionUpdatedEvent
from app.schemas.session import (
    ReorderRequest,
    SessionCreateRequest,
    SessionResponse,
    SessionSummaryResponse,
)
from app.services.participant import participant_service
from app.services.playback import playback_service
from app.services.queue import (
    InvalidOrderError,
    NoActiveRoundError,
    queue_service,
)
from app.services.session import (
    InvalidSessionTransitionError,
    SessionNotFoundError,
    session_service,
)

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


def _join_url(join_code: str) -> str:
    """Build the QR-friendly join URL for a session's join code."""
    base_url = get_settings().public_base_url.rstrip("/")
    return f"{base_url}/join/{join_code}"


def _session_to_response(session: Session) -> SessionResponse:
    """Explicit mapping from the ORM model to the API schema."""
    return SessionResponse(
        id=session.id,
        name=session.name,
        join_code=session.join_code,
        join_url=_join_url(session.join_code),
        status=session.status,
        playback_state=session.playback_state,
        cooldown_seconds=session.cooldown_seconds,
        countdown_seconds=session.countdown_seconds,
        created_at=session.created_at,
        started_at=session.started_at,
        ended_at=session.ended_at,
    )


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreateRequest,
    current_host: Annotated[Host, Depends(get_current_host)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SessionResponse:
    """Create a karaoke session owned by the authenticated host."""
    karaoke = await session_service.create(
        session,
        current_host.id,
        payload.name,
        cooldown_seconds=payload.cooldown_seconds,
        countdown_seconds=payload.countdown_seconds,
    )
    return _session_to_response(karaoke)


@router.get("", response_model=list[SessionResponse])
async def list_sessions(
    current_host: Annotated[Host, Depends(get_current_host)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SessionResponse]:
    """Return the authenticated host's sessions, newest first (M9 dashboard home).

    NOTE: named ``list_sessions`` (not ``get_sessions``) on purpose — see D30
    (endpoint functions must not share a ``__name__`` with a dependency).
    """
    karaoke_sessions = await session_service.list_for_host(session, current_host.id)
    return [_session_to_response(karaoke) for karaoke in karaoke_sessions]


@router.get("/{session_id}", response_model=SessionResponse)
async def session_detail(
    session_id: uuid.UUID,
    current_host: Annotated[Host, Depends(get_current_host)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SessionResponse:
    """Return a session owned by the authenticated host.

    NOTE: named ``session_detail`` (not ``get_session``) on purpose. FastAPI
    0.141 resolves some sub-dependencies by function ``__name__``; a GET
    endpoint literally named ``get_session`` collides with the
    ``app.core.database.get_session`` dependency and breaks ``/start`` and
    ``/end`` routes (see DECISIONS D30).
    """
    try:
        karaoke = await session_service.get_for_host(session, current_host.id, session_id)
    except SessionNotFoundError as exc:
        raise _not_found() from exc
    return _session_to_response(karaoke)


@router.get("/{session_id}/summary", response_model=SessionSummaryResponse)
async def session_summary(
    session_id: uuid.UUID,
    current_host: Annotated[Host, Depends(get_current_host)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SessionSummaryResponse:
    """Return the host's round/session summary (M16).

    Rounds played, the active round, and per-participant song counts
    (submitted / sung / remaining) for the projector dashboard and the
    end-of-night wrap-up.
    """
    try:
        await session_service.get_for_host(session, current_host.id, session_id)
    except SessionNotFoundError as exc:
        raise _not_found() from exc
    return await queue_service.session_summary(session, session_id)


@router.patch("/{session_id}/order", response_model=QueueSnapshotResponse)
async def reorder_session(
    session_id: uuid.UUID,
    payload: ReorderRequest,
    current_host: Annotated[Host, Depends(get_current_host)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QueueSnapshotResponse:
    """Set the host's manual order for the current round (per-round reorder).

    The next round resets to join order. Returns the updated snapshot and
    broadcasts ``QueueUpdated``.
    """
    try:
        await queue_service.reorder(
            session, current_host.id, session_id, payload.participant_names
        )
    except SessionNotFoundError as exc:
        raise _not_found() from exc
    except (InvalidOrderError, NoActiveRoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    snapshot = await queue_service.snapshot(session, session_id)
    await realtime_hub.broadcast(
        session_id, QueueUpdatedEvent(session_id=session_id, snapshot=snapshot)
    )
    return snapshot


@router.delete("/{session_id}/order", response_model=QueueSnapshotResponse)
async def reset_session_order(
    session_id: uuid.UUID,
    current_host: Annotated[Host, Depends(get_current_host)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QueueSnapshotResponse:
    """Clear the current round's reorder (back to join order)."""
    try:
        await queue_service.reset_order(session, current_host.id, session_id)
    except SessionNotFoundError as exc:
        raise _not_found() from exc
    snapshot = await queue_service.snapshot(session, session_id)
    await realtime_hub.broadcast(
        session_id, QueueUpdatedEvent(session_id=session_id, snapshot=snapshot)
    )
    return snapshot


@router.post(
    "/{session_id}/leave", status_code=status.HTTP_204_NO_CONTENT
)
async def leave_session(
    session_id: uuid.UUID,
    participant: Annotated[Participant, Depends(get_current_participant)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Delete the participant and all their songs (leaving the night early).

    The participant's nickname is freed (a rejoin is a fresh identity) and their
    token dies with the row. If they were the current ``SINGING`` singer,
    playback advances to the next singer (E6). The queue updates for everyone
    via ``QueueUpdated``.
    """
    if participant.session_id != session_id:
        raise _not_found()
    was_singing = await participant_service.leave(session, participant)
    if was_singing:
        await playback_service.advance_after_singer_removed(session, session_id)
    await realtime_hub.broadcast(
        session_id,
        QueueUpdatedEvent(
            session_id=session_id,
            snapshot=await queue_service.snapshot(session, session_id),
        ),
    )


@router.post("/{session_id}/start", response_model=SessionResponse)
async def start_session(
    session_id: uuid.UUID,
    current_host: Annotated[Host, Depends(get_current_host)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SessionResponse:
    """Start a session (``CREATED -> ACTIVE``)."""
    try:
        karaoke = await session_service.start(session, current_host.id, session_id)
    except SessionNotFoundError as exc:
        raise _not_found() from exc
    except InvalidSessionTransitionError as exc:
        raise _conflict(str(exc)) from exc
    await realtime_hub.broadcast(
        karaoke.id,
        SessionUpdatedEvent(session_id=karaoke.id, status=karaoke.status),
    )
    return _session_to_response(karaoke)


@router.post("/{session_id}/end", response_model=SessionResponse)
async def end_session(
    session_id: uuid.UUID,
    current_host: Annotated[Host, Depends(get_current_host)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SessionResponse:
    """End a session (any non-terminal state -> ``ENDED``)."""
    try:
        karaoke = await session_service.end(session, current_host.id, session_id)
    except SessionNotFoundError as exc:
        raise _not_found() from exc
    except InvalidSessionTransitionError as exc:
        raise _conflict(str(exc)) from exc
    await realtime_hub.broadcast(
        karaoke.id,
        SessionUpdatedEvent(session_id=karaoke.id, status=karaoke.status),
    )
    return _session_to_response(karaoke)


@router.get("/{session_id}/qr")
async def session_qr(
    session_id: uuid.UUID,
    current_host: Annotated[Host, Depends(get_current_host)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Return an SVG QR code of the session's join URL (decision D32).

    The QR encodes the public join URL (``{KARAOKE_PUBLIC_BASE_URL}/join/{code}``)
    which is what a student's phone opens; the join screen then uses
    ``GET /api/v1/join/{code}`` (M5). Display is the host dashboard's job (M9).
    """
    try:
        karaoke = await session_service.get_for_host(session, current_host.id, session_id)
    except SessionNotFoundError as exc:
        raise _not_found() from exc

    qr = segno.make(_join_url(karaoke.join_code), error="m")
    buffer = io.BytesIO()
    qr.save(buffer, kind="svg", scale=4)
    return Response(content=buffer.getvalue(), media_type="image/svg+xml")


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="session not found"
    )


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
