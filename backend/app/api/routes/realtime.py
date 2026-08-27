"""Realtime WebSocket endpoint (M10).

Subscribes a connection to a session's typed domain events. Authentication
follows API_CONTRACT §8: a bearer token is passed as the ``token`` query
parameter (the browser WebSocket API cannot set request headers). The token
must belong to the session — a participant token must be bound to the session,
a host token must own it — otherwise the connection is closed with code 1008
before it is accepted (no session-existence leak, mirroring decision D29).

The endpoint never sends anything on its own: events arrive via
``RealtimeHub.broadcast`` from the REST routes that mutate domain state. A
reconnecting client must re-fetch authoritative state from the REST API (D5).

A participant's connect refreshes their ``last_connected_at`` (M16 absent-
participant cleanup signal).

Endpoint function name is intentionally distinct from any dependency (D30).
"""

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models.participant import Participant
from app.realtime.hub import realtime_hub
from app.services.host_auth import host_auth_service
from app.services.participant import participant_service
from app.services.session import SessionNotFoundError, session_service

router = APIRouter(prefix="/api/v1/sessions", tags=["realtime"])

#: WebSocket close code for an unauthorized / unbound connection (1008 =
#: policy violation, per RFC 6455).
_POLICY_VIOLATION = 1008


async def _may_connect(
    session: AsyncSession, session_id: uuid.UUID, token: str | None
) -> Participant | None:
    """Return the participant that may subscribe, or None for a host.

    A participant token must belong to the session (returned so the caller can
    refresh ``last_connected_at``); a host token must own it (returns None);
    unknown tokens and cross-session/ownership bindings raise ``ValueError``
    (the caller closes the socket, no existence leak, D29).
    """
    if token is None:
        raise ValueError("missing token")
    participant = await participant_service.get_by_token(session, token)
    if participant is not None:
        if participant.session_id != session_id:
            raise ValueError("participant not bound to this session")
        return participant
    host = await host_auth_service.get_host_by_token(session, token)
    if host is None:
        raise ValueError("unknown token")
    try:
        await session_service.get_for_host(session, host.id, session_id)
    except SessionNotFoundError:
        raise ValueError("host does not own this session")
    return None


@router.websocket("/{session_id}/ws")
async def session_realtime(
    websocket: WebSocket,
    session_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    token: str | None = None,
) -> None:
    """Push typed domain events for a session to this connection."""
    try:
        participant = await _may_connect(session, session_id, token)
    except ValueError:
        await websocket.close(code=_POLICY_VIOLATION)
        return
    if participant is not None:
        participant.last_connected_at = datetime.now(timezone.utc)
        await session.commit()
    await websocket.accept()
    await realtime_hub.connect(session_id, websocket)
    try:
        while True:
            # The client sends no meaningful data; this loop only detects
            # disconnects so the hub can release the connection.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await realtime_hub.disconnect(session_id, websocket)
