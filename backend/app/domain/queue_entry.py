"""Queue entry domain model: status enum (M7).

Mirrors ``docs/DOMAIN_MODEL.md`` §3. Ordering is derived from the entry's
creation timestamp (decision D8); there is no mutable position field.
"""

from enum import Enum


class QueueEntryStatus(str, Enum):
    """Lifecycle state of a queue entry."""

    WAITING = "WAITING"
    NEXT = "NEXT"
    SINGING = "SINGING"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"
    REMOVED = "REMOVED"

    @classmethod
    def non_terminal(cls) -> frozenset["QueueEntryStatus"]:
        """Statuses that count toward the per-participant cap (B15/D45)."""
        return frozenset({cls.WAITING, cls.NEXT, cls.SINGING})
