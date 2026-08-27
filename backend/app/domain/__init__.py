"""Domain layer: domain models, enums, business rules, and state machines.

Holds ``SessionStatus`` (M4, see ``app.domain.session``). QueueEntryStatus,
PlaybackState, and round logic arrive with later milestones (M7/M11/M16).
Kept separate from persistence (``app.models``) and API schemas
(``app.schemas``).
"""
