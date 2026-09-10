"""Song entry endpoints (M6: preview; M7: queue submission and management).

Session-scoped (participant) router:
- ``POST /api/v1/sessions/{id}/entries/preview``  validate + metadata preview (participant)
- ``POST /api/v1/sessions/{id}/entries``           submit a song -> WAITING (participant)
- ``GET  /api/v1/sessions/{id}/entries``           public queue snapshot (no auth)

Entry-scoped router:
- ``DELETE /api/v1/entries/{id}``        cancel own WAITING (participant) or remove (host)
- ``PATCH  /api/v1/entries/{id}/video``  host replaces the YouTube URL (host)

Participant endpoints require the participant's opaque token (M5, D31) and are
scoped to the participant's own session (mismatch -> 404, no existence leak).
Endpoint functions are intentionally NOT named like any dependency (D30).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_current_host,
    get_current_participant,
    get_host_or_participant,
    rate_limit,
)
from app.core.config import get_settings
from app.core.database import get_session
from app.domain.session import SessionStatus
from app.models.host import Host
from app.models.participant import Participant
from app.models.session import Session
from app.realtime.hub import realtime_hub
from app.schemas.queue import (
    QueueEntryResponse,
    QueueSnapshotResponse,
    SongSubmitResponse,
    SongUrlRequest,
)
from app.schemas.realtime import QueueUpdatedEvent
from app.schemas.youtube import (
    SongPreviewRequest,
    SongPreviewResponse,
    YouTubeVideoData,
)
from app.services.queue import (
    DUPLICATE_NOTICE,
    EntryNotCancellableError,
    EntryNotFoundError,
    SongLimitError,
    queue_service,
)
from app.services.playback import playback_service
from app.api.routes.playback import _notify_next_singer
from app.services.session import SessionNotFoundError, session_service
from app.services.youtube import (
    YouTubeQuotaExceededError,
    YouTubeServiceConfigurationError,
    YouTubeVideoUnavailableError,
    extract_video_id,
    long_video_warning,
    youtube_service,
)

router = APIRouter(
    prefix="/api/v1/sessions/{session_id}/entries", tags=["entries"]
)
entry_router = APIRouter(prefix="/api/v1/entries", tags=["entries"])


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="session not found"
    )


def _entry_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="entry not found"
    )


async def _session_for_participant(
    session: AsyncSession, session_id: uuid.UUID, participant: Participant
) -> Session:
    """Load the participant's session, enforcing binding + ended guard."""
    if participant.session_id != session_id:
        raise _not_found()
    try:
        karaoke = await session_service.get_by_id(session, session_id)
    except SessionNotFoundError as exc:
        raise _not_found() from exc
    if karaoke.status is SessionStatus.ENDED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this karaoke night has ended",
        )
    return karaoke


async def _fetch_video_data(
    youtube_url: str, *, allow_quota_fallback: bool = False
) -> YouTubeVideoData:
    """Validate a URL and fetch metadata, translating failures to HTTP errors."""
    video_id = extract_video_id(youtube_url)
    if video_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="that doesn't look like a valid YouTube link",
        )
    try:
        if allow_quota_fallback:
            return await youtube_service.fetch_video_metadata_with_quota_fallback(video_id)
        return await youtube_service.fetch_video_metadata(video_id)
    except YouTubeServiceConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except YouTubeQuotaExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="YouTube quota is temporarily exhausted; try again later",
        ) from exc
    except YouTubeVideoUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="we couldn't load this video",
        ) from exc


async def _position_of(
    session: AsyncSession, session_id: uuid.UUID, entry_id: uuid.UUID
) -> int | None:
    """Compute an entry's 1-based position in the active queue (D8)."""
    active = await queue_service.get_active_entries(session, session_id)
    for index, entry in enumerate(active, start=1):
        if entry.id == entry_id:
            return index
    return None


# --- Session-scoped: preview / submit / snapshot -------------------------------


@router.post("/preview", response_model=SongPreviewResponse)
async def preview_song(
    session_id: uuid.UUID,
    payload: SongPreviewRequest,
    _rate_limited: Annotated[None, Depends(rate_limit("preview", 20, 60))],
    participant: Annotated[Participant, Depends(get_current_participant)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SongPreviewResponse:
    """Validate a YouTube URL and return its metadata + any warning (E3/E4/B6).

    Rate-limited per IP (M17): every preview hits the YouTube Data API (quota).
    """
    await _session_for_participant(session, session_id, participant)
    data = await _fetch_video_data(payload.youtube_url)

    is_long = data.duration_seconds > get_settings().youtube_long_video_seconds
    return SongPreviewResponse(
        youtube_url=data.youtube_url,
        video_id=data.video_id,
        title=data.title,
        channel=data.channel,
        duration_seconds=data.duration_seconds,
        thumbnail_url=data.thumbnail_url,
        is_long=is_long,
        warning=long_video_warning(data.duration_seconds) if is_long else None,
    )


@router.post("", response_model=SongSubmitResponse, status_code=status.HTTP_201_CREATED)
async def submit_song(
    session_id: uuid.UUID,
    payload: SongUrlRequest,
    _rate_limited: Annotated[None, Depends(rate_limit("submit", 20, 60))],
    participant: Annotated[Participant, Depends(get_current_participant)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SongSubmitResponse:
    """Submit a song: validates + re-fetches metadata and creates a WAITING entry.

    Rate-limited per IP (M17): submission re-fetches metadata (YouTube quota).
    """
    await _session_for_participant(session, session_id, participant)
    data = await _fetch_video_data(payload.youtube_url, allow_quota_fallback=True)

    try:
        entry, duplicate = await queue_service.submit(session, participant, data)
    except SongLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    position = await _position_of(session, session_id, entry.id)
    response = SongSubmitResponse(
        entry=queue_service.entry_response(entry, position),
        duplicate=duplicate,
        notice=DUPLICATE_NOTICE if duplicate else None,
    )
    await realtime_hub.broadcast(
        session_id,
        QueueUpdatedEvent(
            session_id=session_id, snapshot=await queue_service.snapshot(session, session_id)
        ),
    )
    return response


@router.get("", response_model=QueueSnapshotResponse)
async def queue_snapshot(
    session_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QueueSnapshotResponse:
    """Public queue snapshot (sanitized; no host identity or participant tokens)."""
    try:
        return await queue_service.snapshot(session, session_id)
    except SessionNotFoundError as exc:
        raise _not_found() from exc


@router.get("/mine", response_model=list[QueueEntryResponse])
async def my_entries(
    session_id: uuid.UUID,
    participant: Annotated[Participant, Depends(get_current_participant)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[QueueEntryResponse]:
    """Return the participant's own queued songs (current + upcoming rounds).

    Order is by round number then submission order. The current-round entry (if
    any) carries its position in the active queue; upcoming songs have
    ``position: null`` (they are not in the active queue until their round,
    M10.1).
    """
    await _session_for_participant(session, session_id, participant)
    entries = await queue_service.get_participant_entries(session, participant)
    return [
        queue_service.entry_response(entry, await _position_of(session, session_id, entry.id))
        for entry in entries
    ]


# --- Entry-scoped: cancel/remove and host edit --------------------------------


@entry_router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    entry_id: uuid.UUID,
    actor: Annotated[Host | Participant, Depends(get_host_or_participant)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Cancel own WAITING entry (participant, B3) or remove any entry (host, B4).

    Removing the current ``SINGING`` entry advances playback to the next
    (E6/M14): the host recovers from a bad live song without database access.
    """
    try:
        was_singing = False
        if isinstance(actor, Participant):
            entry = await queue_service.cancel(session, actor, entry_id)
        else:
            entry, was_singing = await queue_service.remove(
                session, actor.id, entry_id
            )
            if was_singing:
                await playback_service.on_singer_removed(
                    session, actor.id, entry.session_id
                )
    except EntryNotFoundError as exc:
        raise _entry_not_found() from exc
    except EntryNotCancellableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    snapshot = await queue_service.snapshot(session, entry.session_id)
    await realtime_hub.broadcast(
        entry.session_id,
        QueueUpdatedEvent(
            session_id=entry.session_id,
            snapshot=snapshot,
        ),
    )
    if was_singing:
        # M15: removing the current singer promoted the next entry to NEXT and
        # began the countdown (E6) — notify the next singer (both phases).
        await _notify_next_singer(entry.session_id, snapshot, "next")
        await _notify_next_singer(entry.session_id, snapshot, "countdown")


@entry_router.patch("/{entry_id}/video", response_model=QueueEntryResponse)
async def edit_entry_video(
    entry_id: uuid.UUID,
    payload: SongUrlRequest,
    current_host: Annotated[Host, Depends(get_current_host)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QueueEntryResponse:
    """Replace an entry's YouTube URL; the entry keeps its position (B4/E7)."""
    data = await _fetch_video_data(payload.youtube_url)
    try:
        entry = await queue_service.edit_video(session, current_host.id, entry_id, data)
    except EntryNotFoundError as exc:
        raise _entry_not_found() from exc
    position = await _position_of(session, entry.session_id, entry.id)
    response = queue_service.entry_response(entry, position)
    await realtime_hub.broadcast(
        entry.session_id,
        QueueUpdatedEvent(
            session_id=entry.session_id,
            snapshot=await queue_service.snapshot(session, entry.session_id),
        ),
    )
    return response
