"""Service layer: application use-cases and orchestration.

Host auth (M3, ``app.services.host_auth``) and sessions (M4,
``app.services.session``) live here. Services use the database session
directly; a repository layer is deferred until persistence is shared between
services (see docs/DEV_BRAIN.md M3 notes).
"""
