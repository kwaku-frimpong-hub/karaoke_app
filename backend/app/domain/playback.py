"""Playback domain model: state enum (M11; transitions at M13).

``PlaybackState`` is the playback lifecycle of the session's single playback
device (the host browser). It mirrors ``docs/DOMAIN_MODEL.md`` §3. The full
documented lifecycle is encoded here; M11 reaches ``IDLE``/``PLAYING`` and M13
reaches the automatic-transition states (``COOLDOWN``/``COUNTDOWN``). The state
is **stored** on the session (decision D47) because the transition states cannot
be derived from entry statuses alone.
"""

from datetime import datetime, timezone
from enum import Enum


class PlaybackState(str, Enum):
    """Lifecycle state of the host-device playback (stored, decision D47)."""

    IDLE = "IDLE"
    PREPARING = "PREPARING"
    COUNTDOWN = "COUNTDOWN"
    PLAYING = "PLAYING"
    COOLDOWN = "COOLDOWN"
    FINISHED = "FINISHED"
    SKIPPED = "SKIPPED"

    @classmethod
    def transition_states(cls) -> frozenset["PlaybackState"]:
        """States that represent an in-flight automatic transition (M13)."""
        return frozenset({cls.COOLDOWN, cls.COUNTDOWN})


def ensure_utc(value: datetime) -> datetime:
    """Return ``value`` normalized to an aware UTC datetime.

    SQLite stores ``DateTime(timezone=True)`` columns without the UTC offset and
    reads them back naive; PostgreSQL reads them back aware. Normalizing keeps
    comparisons and subtractions against ``datetime.now(timezone.utc)`` safe on
    both the SQLite test suite and PostgreSQL (D22).
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
