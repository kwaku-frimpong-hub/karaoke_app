"""Host participant management endpoints.

These endpoints let the host manage singers who cannot use the QR flow: list the
session's participants and queued songs, create a participant by nickname, and
add a YouTube song to a participant's queue. The backend/database remains the
single source of truth; the host UI only renders these authoritative responses.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_host
from app.api.routes.entries import _fetch_video_data, _position_of
from app.core.database import get_session
from app.domain.session import SessionStatus
from app.models.host import Host
from app.models.participant import Participant
from app.realtime.hub import realtime_hub
from app.schemas.participant import (
    HostParticipantDetailResponse,
    ParticipantCreateRequest,
    ParticipantResponse,
)
from app.schemas.queue import SongSubmitResponse, SongUrlRequest
from app.schemas.realtime import ParticipantJoinedEvent, QueueUpdatedEvent
from app.services.participant import (
    InvalidNicknameError,
    NicknameTakenError,
    ParticipantNotFoundError,
    SessionEndedError,
    participant_service,
)
from app.services.queue import DUPLICATE_NOTICE, SongLimitError, queue_service
from app.services.session import SessionNotFoundError, session_service

router = APIRouter(
    prefix="/api/v1/sessions/{session_id}/participants",
    tags=["participants"],
)


def _participant_to_response(participant: Participant) -> ParticipantResponse:
    """Explicit mapping from ORM model to the participant API schema."""
    return ParticipantResponse(
        id=participant.id,
        session_id=participant.session_id,
        nickname=participant.nickname,
        created_at=participant.created_at,
    )


def _session_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="session not found"
    )


def _participant_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="participant not found"
    )


async def _host_session(
    session: AsyncSession, host: Host, session_id: uuid.UUID
) -> None:
    """Enforce host ownership and reject ended sessions for mutations."""
    try:
        karaoke = await session_service.get_for_host(session, host.id, session_id)
    except SessionNotFoundError as exc:
        raise _session_not_found() from exc
    if karaoke.status is SessionStatus.ENDED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this karaoke night has ended",
        )


@router.get("", response_model=list[HostParticipantDetailResponse])
async def list_session_participants(
    session_id: uuid.UUID,
    current_host: Annotated[Host, Depends(get_current_host)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[HostParticipantDetailResponse]:
    """Return host-facing participants with their queued playlists."""
    try:
        await session_service.get_for_host(session, current_host.id, session_id)
    except SessionNotFoundError as exc:
        raise _session_not_found() from exc
    return await queue_service.participant_details(session, session_id)


@router.post(
    "",
    response_model=ParticipantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session_participant(
    session_id: uuid.UUID,
    payload: ParticipantCreateRequest,
    current_host: Annotated[Host, Depends(get_current_host)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ParticipantResponse:
    """Create a participant on behalf of someone without a phone."""
    await _host_session(session, current_host, session_id)
    try:
        participant, _raw_token = await participant_service.register_in_session(
            session, session_id, payload.nickname
        )
    except SessionNotFoundError as exc:
        raise _session_not_found() from exc
    except SessionEndedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this karaoke night has ended",
        ) from exc
    except InvalidNicknameError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except NicknameTakenError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"nickname '{exc.args[0]}' is already taken",
        ) from exc
    await realtime_hub.broadcast(
        session_id,
        ParticipantJoinedEvent(session_id=session_id, nickname=participant.nickname),
    )
    return _participant_to_response(participant)


@router.post(
    "/{participant_id}/entries",
    response_model=SongSubmitResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_participant_song(
    session_id: uuid.UUID,
    participant_id: uuid.UUID,
    payload: SongUrlRequest,
    current_host: Annotated[Host, Depends(get_current_host)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SongSubmitResponse:
    """Host adds a song to a participant's queued playlist."""
    await _host_session(session, current_host, session_id)
    try:
        participant = await participant_service.get_in_session(
            session, session_id, participant_id
        )
    except ParticipantNotFoundError as exc:
        raise _participant_not_found() from exc
    data = await _fetch_video_data(payload.youtube_url, allow_quota_fallback=True)
    try:
        entry, duplicate = await queue_service.submit(session, participant, data)
    except SongLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    response = SongSubmitResponse(
        entry=queue_service.entry_response(
            entry, await _position_of(session, session_id, entry.id)
        ),
        duplicate=duplicate,
        notice=DUPLICATE_NOTICE if duplicate else None,
    )
    await realtime_hub.broadcast(
        session_id,
        QueueUpdatedEvent(
            session_id=session_id,
            snapshot=await queue_service.snapshot(session, session_id),
        ),
    )
    return response
