"""Playback use-cases (M11; automatic transitions at M13).

The playback state machine is host-driven (M11) and, since M13, **automatically
advances** between songs using per-session timing configuration (PRODUCT_SPEC
§10): when a song ends (``end``) the backend enters ``COOLDOWN``, then
``COUNTDOWN``, then auto-promotes the next entry to ``SINGING`` (``PLAYING``).
Host ``skip``/``finish`` skip the cooldown and go straight to the countdown
(D20: advance immediately — no post-song rest after a host intervention).

Timing is backend-authoritative (D2): the session stores ``playback_state`` and
the absolute ``transition_until`` deadline (decision D47). The frontend renders
the remaining time from the snapshot and calls ``advance`` when a phase's
deadline passes — the endpoint advances idempotently, so a disconnected/reopened
dashboard simply sees an overdue deadline and calls ``advance`` again. There are
no background timers, so nothing drifts or leaks across restarts.

``playback_state`` is stored because the transition states cannot be derived
from entry statuses alone (this supersedes M11/D46's derived state). The service
keeps the stored state and the entry statuses consistent:
- ``PLAYING``  <-> an entry is ``SINGING``
- ``COOLDOWN``/``COUNTDOWN`` -> the front of the active queue is ``NEXT``
- ``IDLE``     -> nothing is singing and no transition is pending

Pause/resume are session transitions (``ACTIVE <-> PAUSED``) in
``SessionService``; pausing cancels any pending transition (the host controls
the next start manually after resume, E22).
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.playback import PlaybackState, ensure_utc
from app.domain.queue_entry import QueueEntryStatus
from app.domain.session import SessionStatus
from app.models.queue_entry import QueueEntry
from app.models.session import Session
from app.services.queue import queue_service
from app.services.session import SessionNotFoundError, session_service


class SessionEndedError(Exception):
    """Raised when a playback action targets an ended session."""


class NothingToPlayError(Exception):
    """Raised when starting playback with an empty active queue."""


class AlreadyPlayingError(Exception):
    """Raised when starting a song while one is already ``SINGING``."""


class NothingPlayingError(Exception):
    """Raised when skipping/finishing with no ``SINGING`` entry."""


class TransitionNotReadyError(Exception):
    """Raised when advancing a transition before its deadline passes."""


class NoTransitionError(Exception):
    """Raised when advancing while no transition is in progress."""


class PlaybackService:
    """Application service for playback (M11) and automatic transitions (M13)."""

    async def start(
        self, session: AsyncSession, host_id: uuid.UUID, session_id: uuid.UUID
    ) -> QueueEntry:
        """Manually start the front of the active queue (→ ``SINGING``).

        Cancels any pending automatic transition (the host overrides automation,
        B9). Raises ``NothingToPlayError``, ``AlreadyPlayingError``, or
        ``SessionEndedError``.
        """
        karaoke = await self._require_playable(session, host_id, session_id)
        active = await queue_service.get_active_entries(session, session_id)
        if not active:
            raise NothingToPlayError("the queue is empty")
        current = active[0]
        if current.status is QueueEntryStatus.SINGING:
            raise AlreadyPlayingError("a song is already playing")
        current.status = QueueEntryStatus.SINGING
        current.started_at = datetime.now(timezone.utc)
        karaoke.playback_state = PlaybackState.PLAYING
        karaoke.transition_until = None
        await session.commit()
        return current

    async def end(
        self, session: AsyncSession, host_id: uuid.UUID, session_id: uuid.UUID
    ) -> QueueEntry:
        """The host device reports the current video ended naturally (M13).

        Marks the entry ``COMPLETED``, promotes the next to ``NEXT``, and begins
        the automatic transition with the post-song cooldown.
        """
        karaoke = await self._require_playable(session, host_id, session_id)
        current = await self._current_singer(session, session_id)
        if current is None:
            raise NothingPlayingError("no song is currently playing")
        current.status = QueueEntryStatus.COMPLETED
        current.ended_at = datetime.now(timezone.utc)
        await session.commit()
        await self._promote_next(session, session_id)
        await self._begin_transition(session, karaoke, skip_cooldown=False)
        await session.commit()
        return current

    async def skip(
        self, session: AsyncSession, host_id: uuid.UUID, session_id: uuid.UUID
    ) -> QueueEntry:
        """Move the current singer to the end of the round (queue revision).

        The singer gets one re-chance after everyone else: the entry returns to
        ``WAITING`` with ``skip_count`` incremented (so it sorts last). If the
        singer is the **only** non-terminal entry left in the round, they are
        excluded (``SKIPPED``) so the round can complete. Either way the next
        singer is promoted and the countdown transition begins (no cooldown —
        host intervention, D20).
        """
        karaoke = await self._require_playable(session, host_id, session_id)
        current = await self._current_singer(session, session_id)
        if current is None:
            raise NothingPlayingError("no song is currently playing")
        active = await queue_service.get_active_entries(session, session_id)
        if len(active) <= 1:
            # The only singer left: skipping must exclude them or the round
            # would never complete.
            current.status = QueueEntryStatus.SKIPPED
            current.ended_at = datetime.now(timezone.utc)
        else:
            # Move to the end of the round (one re-chance).
            current.skip_count += 1
            current.status = QueueEntryStatus.WAITING
            current.started_at = None
            current.ended_at = None
        await session.commit()
        await self._promote_next(session, session_id)
        await self._begin_transition(session, karaoke, skip_cooldown=True)
        await session.commit()
        return current

    async def finish(
        self, session: AsyncSession, host_id: uuid.UUID, session_id: uuid.UUID
    ) -> QueueEntry:
        """Finish the current singer (``COMPLETED``) and begin the countdown (D20/M13)."""
        return await self._advance(
            session, host_id, session_id, QueueEntryStatus.COMPLETED
        )

    async def advance(
        self, session: AsyncSession, host_id: uuid.UUID, session_id: uuid.UUID
    ) -> QueueEntry | None:
        """Progress an automatic transition whose phase deadline has passed.

        ``COOLDOWN`` -> ``COUNTDOWN`` (returns None), then ``COUNTDOWN`` ->
        ``PLAYING`` (auto-promotes the ``NEXT`` entry to ``SINGING`` and returns
        it). Idempotent: calling advance again after the transition finished
        raises ``NoTransitionError``; calling it before a deadline raises
        ``TransitionNotReadyError``. The host dashboard calls this when its
        local countdown reaches zero, so a reopened tab self-recovers.
        """
        karaoke = await self._require_playable(session, host_id, session_id)
        now_ = datetime.now(timezone.utc)
        if karaoke.playback_state is PlaybackState.COOLDOWN:
            if (
                karaoke.transition_until is not None
                and now_ < ensure_utc(karaoke.transition_until)
            ):
                raise TransitionNotReadyError("cooldown is still running")
            karaoke.playback_state = PlaybackState.COUNTDOWN
            karaoke.transition_until = now_ + timedelta(
                seconds=karaoke.countdown_seconds
            )
            await session.commit()
            return None
        if karaoke.playback_state is PlaybackState.COUNTDOWN:
            if (
                karaoke.transition_until is not None
                and now_ < ensure_utc(karaoke.transition_until)
            ):
                raise TransitionNotReadyError("countdown is still running")
            entry = await self._start_front(session, karaoke)
            # If the queue emptied mid-countdown (the host removed the NEXT
            # entry), there is nothing to start: return to IDLE rather than
            # claiming PLAYING with no singer (D47 invariant).
            karaoke.playback_state = (
                PlaybackState.PLAYING if entry is not None else PlaybackState.IDLE
            )
            karaoke.transition_until = None
            await session.commit()
            return entry
        raise NoTransitionError("no automatic transition in progress")

    async def pause(
        self, session: AsyncSession, host_id: uuid.UUID, session_id: uuid.UUID
    ) -> Session:
        """Pause automatic progression (``ACTIVE -> PAUSED``) and cancel any
        pending transition (E22: the host starts the next song manually)."""
        karaoke = await session_service.pause(session, host_id, session_id)
        if karaoke.playback_state in PlaybackState.transition_states():
            karaoke.playback_state = PlaybackState.IDLE
            karaoke.transition_until = None
            await session.commit()
        return karaoke

    async def resume(
        self, session: AsyncSession, host_id: uuid.UUID, session_id: uuid.UUID
    ) -> Session:
        """Resume progression (``PAUSED -> ACTIVE``, M11/M13)."""
        return await session_service.resume(session, host_id, session_id)

    # --- internals -------------------------------------------------------------

    async def on_singer_removed(
        self, session: AsyncSession, host_id: uuid.UUID, session_id: uuid.UUID
    ) -> None:
        """Advance playback after the host removed the current ``SINGING`` entry.

        The entry is already ``REMOVED`` (E6): promote the new front to ``NEXT``
        and begin the countdown transition — a host intervention skips the
        post-song cooldown (D20). If no entry remains, playback returns to
        ``IDLE``. On an ended session (cleanup) there is no playback to advance.
        """
        await session_service.get_for_host(session, host_id, session_id)
        await self._advance_after_singer_terminal(session, session_id)

    async def advance_after_singer_removed(
        self, session: AsyncSession, session_id: uuid.UUID
    ) -> None:
        """Advance playback after the current singer left the session (E6).

        Same behavior as ``on_singer_removed`` but for a participant leaving:
        no host ownership check (the caller already bound the participant).
        """
        await self._advance_after_singer_terminal(session, session_id)

    async def _advance_after_singer_terminal(
        self, session: AsyncSession, session_id: uuid.UUID
    ) -> None:
        karaoke = await session_service.get_by_id(session, session_id)
        if karaoke.status is SessionStatus.ENDED:
            return
        await self._promote_next(session, session_id)
        await self._begin_transition(session, karaoke, skip_cooldown=True)
        await session.commit()

    async def _advance(
        self,
        session: AsyncSession,
        host_id: uuid.UUID,
        session_id: uuid.UUID,
        terminal: QueueEntryStatus,
    ) -> QueueEntry:
        """Mark the current singer terminal and begin the countdown transition.

        Host interventions (skip/finish) skip the post-song cooldown: the singer
        is done, keep momentum, but the next singer still gets their countdown.
        """
        karaoke = await self._require_playable(session, host_id, session_id)
        current = await self._current_singer(session, session_id)
        if current is None:
            raise NothingPlayingError("no song is currently playing")
        current.status = terminal
        current.ended_at = datetime.now(timezone.utc)
        await session.commit()
        await self._promote_next(session, session_id)
        await self._begin_transition(session, karaoke, skip_cooldown=True)
        await session.commit()
        return current

    async def _begin_transition(
        self,
        session: AsyncSession,
        karaoke: Session,
        skip_cooldown: bool,
    ) -> None:
        """Set the playback state for the next phase of the transition.

        When no entry remains (the queue is exhausted), the transition is a
        no-op: playback returns to ``IDLE``.
        """
        active = await queue_service.get_active_entries(session, karaoke.id)
        if not active:
            karaoke.playback_state = PlaybackState.IDLE
            karaoke.transition_until = None
            return
        now_ = datetime.now(timezone.utc)
        if skip_cooldown or karaoke.cooldown_seconds == 0:
            karaoke.playback_state = PlaybackState.COUNTDOWN
            karaoke.transition_until = now_ + timedelta(
                seconds=karaoke.countdown_seconds
            )
        else:
            karaoke.playback_state = PlaybackState.COOLDOWN
            karaoke.transition_until = now_ + timedelta(
                seconds=karaoke.cooldown_seconds
            )

    async def _start_front(
        self, session: AsyncSession, karaoke: Session
    ) -> QueueEntry | None:
        """Promote the front of the active queue to ``SINGING`` (auto-start)."""
        active = await queue_service.get_active_entries(session, karaoke.id)
        if not active:
            return None
        current = active[0]
        current.status = QueueEntryStatus.SINGING
        current.started_at = datetime.now(timezone.utc)
        return current

    async def _promote_next(
        self, session: AsyncSession, session_id: uuid.UUID
    ) -> None:
        """Promote the new front of the active queue to ``NEXT``.

        Runs after the current entry becomes terminal, so it also crosses into
        the next round automatically when the current round is exhausted (M10.1).
        """
        remaining = await queue_service.get_active_entries(session, session_id)
        if remaining:
            remaining[0].status = QueueEntryStatus.NEXT
            await session.commit()

    async def _current_singer(
        self, session: AsyncSession, session_id: uuid.UUID
    ) -> QueueEntry | None:
        active = await queue_service.get_active_entries(session, session_id)
        return next(
            (e for e in active if e.status is QueueEntryStatus.SINGING), None
        )

    async def _require_playable(
        self, session: AsyncSession, host_id: uuid.UUID, session_id: uuid.UUID
    ) -> Session:
        """Return the host's session, rejecting ended sessions (no existence
        leak: unknown/other-host sessions raise ``SessionNotFoundError``)."""
        karaoke = await session_service.get_for_host(session, host_id, session_id)
        if karaoke.status is SessionStatus.ENDED:
            raise SessionEndedError("this karaoke night has ended")
        return karaoke


playback_service = PlaybackService()
