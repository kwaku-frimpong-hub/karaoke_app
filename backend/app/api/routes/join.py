"""Public join endpoints (M5).

Anyone with a join code can look up a session and register a participant
identity — no account, no bearer token (rule B2, decision D6). The QR code
(M4 join URL, D32) encodes ``{public_base_url}/join/{join_code}``, which this
router serves at the API level.

- ``GET  /api/v1/join/{join_code}``             public session snapshot
- ``POST /api/v1/join/{join_code}/participants`` register a participant

Endpoint functions are intentionally NOT named ``get_session`` (FastAPI
0.141.1 resolves some dependencies by function ``__name__``; see D30).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import rate_limit
from app.core.database import get_session
from app.models.participant import Participant
from app.models.session import Session
from app.realtime.hub import realtime_hub
from app.schemas.participant import (
    JoinSessionResponse,
    ParticipantCreateRequest,
    ParticipantJoinResponse,
    ParticipantResponse,
)
from app.schemas.realtime import ParticipantJoinedEvent
from app.services.participant import (
    InvalidNicknameError,
    NicknameTakenError,
    SessionEndedError,
    participant_service,
)
from app.services.session import SessionNotFoundError

router = APIRouter(prefix="/api/v1/join", tags=["join"])


def _session_to_join_response(session: Session) -> JoinSessionResponse:
    """Explicit mapping from the ORM model to the public join snapshot."""
    return JoinSessionResponse(
        id=session.id, name=session.name, status=session.status
    )


def _participant_to_response(participant: Participant) -> ParticipantResponse:
    """Explicit mapping from the ORM model to the API schema."""
    return ParticipantResponse(
        id=participant.id,
        session_id=participant.session_id,
        nickname=participant.nickname,
        created_at=participant.created_at,
    )


@router.get("/{join_code}", response_model=JoinSessionResponse)
async def lookup_session(
    join_code: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JoinSessionResponse:
    """Return the public snapshot of the session behind a join code.

    An ended session is still returned (status ``ENDED``) so the join screen
    can render "This karaoke night has ended" (E18); registration is rejected
    separately.
    """
    try:
        karaoke = await participant_service.get_session_for_join(session, join_code)
    except SessionNotFoundError as exc:
        raise _not_found() from exc
    return _session_to_join_response(karaoke)


@router.post(
    "/{join_code}/participants",
    response_model=ParticipantJoinResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_participant(
    join_code: str,
    payload: ParticipantCreateRequest,
    _rate_limited: Annotated[None, Depends(rate_limit("join", 10, 60))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ParticipantJoinResponse:
    """Register a participant by nickname and return their opaque token.

    Rate-limited per IP (M17): the join endpoint is public (anyone with the QR
    code), so it is the main abuse surface of the night.
    """
    try:
        participant, raw_token = await participant_service.register(
            session, join_code, payload.nickname
        )
        # Re-fetches the already-loaded Session via SQLAlchemy's identity map
        # (no extra query); kept inside the try so a concurrent deletion would
        # still surface as 404 rather than 500.
        karaoke = await participant_service.get_session_for_join(session, join_code)
    except SessionNotFoundError as exc:
        raise _not_found() from exc
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
        karaoke.id,
        ParticipantJoinedEvent(session_id=karaoke.id, nickname=participant.nickname),
    )
    return ParticipantJoinResponse(
        token=raw_token,
        session=_session_to_join_response(karaoke),
        participant=_participant_to_response(participant),
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="session not found"
    )
