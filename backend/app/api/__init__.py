"""HTTP and WebSocket endpoints.

Routers live in ``app.api.routes``. Endpoints are thin: they validate with
Pydantic schemas and delegate to ``app.services`` (populated from M4 onward).
"""
