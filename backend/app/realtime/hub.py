"""In-process realtime delivery hub (M10).

WebSockets are a delivery mechanism, not the source of truth (decision D5):
``RealtimeHub`` broadcasts typed domain events to every connection subscribed
to a session, and reconnecting clients must re-fetch authoritative state from
the REST API. The hub never persists anything and never decides state.

The hub is in-process and per-worker (no Redis in v1, decision D9): it fits the
single-worker uvicorn used for local development and the school deployment. A
shared hub (e.g. Redis pub/sub) is only needed if the backend ever runs more
than one worker process.
"""

import asyncio
import uuid
from collections import defaultdict

from fastapi import WebSocket

from app.schemas.realtime import RealtimeEvent


class RealtimeHub:
    """Broadcast typed events to the WebSocket subscribers of a session."""

    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)
        # A single lock guards the connection registry AND serializes
        # broadcasts, so a slow or failing client cannot corrupt concurrent
        # sends to the same connection.
        self._lock = asyncio.Lock()

    async def connect(self, session_id: uuid.UUID, websocket: WebSocket) -> None:
        """Register a connection as a subscriber of ``session_id``."""
        async with self._lock:
            self._connections[session_id].add(websocket)

    async def disconnect(self, session_id: uuid.UUID, websocket: WebSocket) -> None:
        """Unregister a connection; drop the bucket when it becomes empty."""
        async with self._lock:
            connections = self._connections.get(session_id)
            if connections is None:
                return
            connections.discard(websocket)
            if not connections:
                del self._connections[session_id]

    async def broadcast(self, session_id: uuid.UUID, event: RealtimeEvent) -> None:
        """Send ``event`` (JSON) to every subscriber of ``session_id``.

        Dead connections are dropped without raising: a broken subscriber must
        never break a broadcast for the rest of the session.
        """
        message = event.model_dump_json()
        stale: list[WebSocket] = []
        async with self._lock:
            connections = list(self._connections.get(session_id, ()))
            for websocket in connections:
                try:
                    await websocket.send_text(message)
                except Exception:
                    # The client is gone or unreachable. Drop it here while we
                    # already hold the lock (do not recurse into disconnect()).
                    stale.append(websocket)
            if stale:
                remaining = self._connections[session_id]
                for websocket in stale:
                    remaining.discard(websocket)
                if not remaining:
                    del self._connections[session_id]


#: Module-level singleton shared by the WebSocket endpoint and the REST routes.
realtime_hub = RealtimeHub()
