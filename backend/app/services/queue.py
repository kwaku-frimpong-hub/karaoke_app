"""Queue management use-cases (M7; round-robin engine at M10.1; queue revision).

The authoritative queue engine: submissions (with the per-participant song cap
and duplicate notice), public snapshots of the current round with computed
positions, participant cancellation, and host removal/URL editing.

Since M10.1 (decisions D43–D45) the queue is **round-robin**: round N holds one
song per participant (their N-th song); the active round is derived (the
lowest-numbered round with a non-terminal entry) and advances automatically when
it empties. Within a round the order is the **join order** (earliest join first)
unless the host reorders the current round, and a skipped singer is moved to the
end via ``skip_count`` (queue revision).
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.playback import ensure_utc
from app.domain.queue_entry import QueueEntryStatus
from app.domain.session import SessionStatus
from app.models.participant import Participant
from app.models.queue_entry import QueueEntry
from app.models.round import Round
from app.models.round_order import RoundOrder
from app.models.session import Session
from app.models.youtube_video import YouTubeVideo
from app.schemas.participant import (
    HostParticipantDetailResponse,
    HostParticipantEntryResponse,
)
from app.schemas.queue import QueueEntryResponse, QueueParticipant, QueueSnapshotResponse
from app.schemas.session import SessionParticipantSummary, SessionSummaryResponse
from app.schemas.youtube import YouTubeVideoData
from app.services.session import SessionNotFoundError, session_service

#: Informational notice for a duplicate song (B16/D15 — never a block).
DUPLICATE_NOTICE = "This song is already in the queue."


class SongLimitError(Exception):
    """Raised when a participant has reached the total song cap (B15/D45)."""


class EntryNotFoundError(Exception):
    """Raised when an entry does not exist or the actor cannot act on it."""


class EntryNotCancellableError(Exception):
    """Raised when a participant tries to cancel an entry that is not WAITING."""


class InvalidOrderError(Exception):
    """Raised when a reorder references unknown or duplicate nicknames."""


class NoActiveRoundError(Exception):
    """Raised when there is no active round to reorder (the queue is empty)."""


class QueueService:
    """Application service for the round-robin queue."""

    async def submit(
        self,
        session: AsyncSession,
        participant: Participant,
        data: YouTubeVideoData,
    ) -> tuple[QueueEntry, bool]:
        """Queue a song and return ``(entry, duplicate)``.

        The entry is assigned to a round (D43): the current round when the
        participant has no non-terminal entry there, otherwise the next round
        above their highest round. ``duplicate`` is True when the same video is
        already queued anywhere in the session (informational only, B16).
        Raises ``SongLimitError`` at the per-participant total cap (B15/D45).
        """
        cap = get_settings().queue_max_songs_per_participant
        total = await session.scalar(
            select(func.count(QueueEntry.id)).where(
                QueueEntry.session_id == participant.session_id,
                QueueEntry.participant_id == participant.id,
                QueueEntry.status.in_(QueueEntryStatus.non_terminal()),
            )
        )
        if (total or 0) >= cap:
            raise SongLimitError(
                f"you can have at most {cap} songs in the queue"
            )

        karaoke_round = await self._target_round(session, participant)

        duplicate = (
            await session.scalar(
                select(QueueEntry.id)
                .join(YouTubeVideo, QueueEntry.youtube_video_id == YouTubeVideo.id)
                .where(
                    QueueEntry.session_id == participant.session_id,
                    QueueEntry.status.in_(QueueEntryStatus.non_terminal()),
                    YouTubeVideo.youtube_video_id == data.video_id,
                )
            )
        ) is not None

        video = await self._get_or_create_video(session, data)
        entry = QueueEntry(
            session_id=participant.session_id,
            round_id=karaoke_round.id,
            participant_id=participant.id,
            youtube_video_id=video.id,
            status=QueueEntryStatus.WAITING,
        )
        session.add(entry)
        await session.commit()
        return await self.get_entry(session, entry.id), duplicate

    async def get_active_entries(
        self, session: AsyncSession, session_id: uuid.UUID
    ) -> list[QueueEntry]:
        """Return the current round's non-terminal entries in queue order.

        The current round is the lowest-numbered round with a non-terminal entry
        (derived, D43). Order within the round (queue revision):

        - entries that were skipped-and-moved go last, by ``skip_count``;
        - if the host reordered this round, the reorder positions win;
        - otherwise the order is the **participant join order** (earliest join
          first), with ``created_at``/``id`` as the deterministic tie-break.

        Computed in the service (school-night scale) so the join-order and
        reorder fallbacks stay dialect-portable (D22).
        """
        karaoke_round = await self._active_round(session, session_id)
        if karaoke_round is None:
            return []
        result = await session.scalars(
            select(QueueEntry).where(
                QueueEntry.round_id == karaoke_round.id,
                QueueEntry.status.in_(QueueEntryStatus.non_terminal()),
            )
        )
        entries = list(result)
        if not entries:
            return []
        join_index = await self._join_index_map(session, session_id)
        reorder = await self._round_order_map(session, karaoke_round.id)
        n_reordered = len(reorder) if reorder is not None else 0

        def sort_key(entry: QueueEntry) -> tuple:
            if reorder is not None and entry.participant_id in reorder:
                base = reorder[entry.participant_id]
            else:
                # Late additions (or a reorder that didn't list everyone) sort
                # after all reordered participants, then by join order.
                base = n_reordered + join_index.get(entry.participant_id, n_reordered)
            return (entry.skip_count, base, entry.created_at, entry.id)

        entries.sort(key=sort_key)
        return entries

    async def get_participant_entries(
        self, session: AsyncSession, participant: Participant
    ) -> list[QueueEntry]:
        """Return a participant's own non-terminal entries across all rounds.

        Ordered by round number then submission order: the entry in the current
        round (if any) comes first, followed by upcoming songs for later rounds
        (M10.1 "my songs").
        """
        result = await session.scalars(
            select(QueueEntry)
            .join(Round, QueueEntry.round_id == Round.id)
            .where(
                QueueEntry.session_id == participant.session_id,
                QueueEntry.participant_id == participant.id,
                QueueEntry.status.in_(QueueEntryStatus.non_terminal()),
            )
            .order_by(Round.number, QueueEntry.created_at, QueueEntry.id)
        )
        return list(result)

    async def get_current_round_number(
        self, session: AsyncSession, session_id: uuid.UUID
    ) -> int:
        """Return the active round number for display.

        The active round is the lowest-numbered round with a non-terminal entry;
        when the queue is empty the highest round that exists is returned (1 for
        a fresh session).
        """
        active = await self._active_round(session, session_id)
        if active is not None:
            return active.number
        highest = await session.scalar(
            select(func.max(Round.number)).where(Round.session_id == session_id)
        )
        return highest if highest is not None else 1

    def entry_response(
        self, entry: QueueEntry, position: int | None
    ) -> QueueEntryResponse:
        """Explicit mapping from the ORM model to the API schema.

        Shared by the REST snapshot and the realtime ``QueueUpdated`` payloads.
        """
        return QueueEntryResponse(
            id=entry.id,
            participant_name=entry.participant.nickname,
            status=entry.status,
            video_id=entry.youtube_video.youtube_video_id,
            youtube_url=entry.youtube_video.youtube_url,
            title=entry.youtube_video.title,
            channel=entry.youtube_video.channel,
            duration_seconds=entry.youtube_video.duration_seconds,
            thumbnail_url=entry.youtube_video.thumbnail_url,
            position=position,
            created_at=entry.created_at,
        )

    async def snapshot(
        self, session: AsyncSession, session_id: uuid.UUID
    ) -> QueueSnapshotResponse:
        """Return the authoritative queue snapshot (REST + realtime, M11/M13/M16).

        Runs the absent-participant cleanup first (M16) so the rendered queue
        never shows ghost entries; ``playback_state`` is the stored state (D47);
        ``transition_remaining_seconds`` is computed from the authoritative
        deadline.
        """
        await self.cleanup_absent_participants(session, session_id)
        karaoke = await session_service.get_by_id(session, session_id)
        active = await self.get_active_entries(session, session_id)
        remaining: float | None = None
        if karaoke.transition_until is not None:
            remaining = max(
                0.0,
                (
                    ensure_utc(karaoke.transition_until)
                    - datetime.now(timezone.utc)
                ).total_seconds(),
            )
        return QueueSnapshotResponse(
            session_id=karaoke.id,
            status=karaoke.status,
            round_number=await self.get_current_round_number(session, session_id),
            rounds_completed=await self.rounds_completed(session, session_id),
            playback_state=karaoke.playback_state,
            transition_until=karaoke.transition_until,
            transition_remaining_seconds=remaining,
            cooldown_seconds=karaoke.cooldown_seconds,
            countdown_seconds=karaoke.countdown_seconds,
            participants=await self.participant_summaries(session, session_id),
            queue=[
                self.entry_response(entry, index)
                for index, entry in enumerate(active, start=1)
            ],
        )

    async def cleanup_absent_participants(
        self, session: AsyncSession, session_id: uuid.UUID
    ) -> None:
        """Mark the remaining WAITING entries of absent participants CANCELLED.

        A participant is absent when they have not connected to the realtime
        channel for ``KARAOKE_ABSENT_PARTICIPANT_CLEANUP_SECONDS`` (default
        30 min, M16). The cleanup runs lazily whenever the authoritative
        snapshot is built; it is idempotent and cheap when nobody is stale.
        Only WAITING entries are cleaned — an absent ``NEXT``/``SINGING``
        singer is the host's skip call (E2/E6).
        """
        karaoke = await session_service.get_by_id(session, session_id)
        if karaoke.status not in (SessionStatus.ACTIVE, SessionStatus.PAUSED):
            return
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=get_settings().absent_participant_cleanup_seconds
        )
        participants = await session.scalars(
            select(Participant).where(Participant.session_id == session_id)
        )
        stale_ids = [
            participant.id
            for participant in participants
            if participant.last_connected_at is not None
            and ensure_utc(participant.last_connected_at) < cutoff
        ]
        if not stale_ids:
            return
        entries = await session.scalars(
            select(QueueEntry).where(
                QueueEntry.session_id == session_id,
                QueueEntry.participant_id.in_(stale_ids),
                QueueEntry.status == QueueEntryStatus.WAITING,
            )
        )
        now = datetime.now(timezone.utc)
        changed = False
        for entry in entries:
            entry.status = QueueEntryStatus.CANCELLED
            entry.ended_at = now
            changed = True
        if changed:
            await session.commit()

    async def rounds_completed(
        self, session: AsyncSession, session_id: uuid.UUID
    ) -> int:
        """Return how many rounds have been fully played (M16).

        The active round is the lowest with a non-terminal entry (D43), so every
        round below it is complete; when nothing is queued, every round that has
        ever held an entry is complete.
        """
        active = await self._active_round(session, session_id)
        if active is not None:
            return max(0, active.number - 1)
        highest = await session.scalar(
            select(func.max(Round.number))
            .join(QueueEntry, QueueEntry.round_id == Round.id)
            .where(Round.session_id == session_id)
        )
        return highest if highest is not None else 0

    async def participant_summaries(
        self, session: AsyncSession, session_id: uuid.UUID
    ) -> list[QueueParticipant]:
        """Per-participant remaining-song counts (M16).

        Ordered by participant join order. Only participants with at least one
        non-terminal entry appear.
        """
        rows = await session.execute(
            select(Participant.nickname, func.count(QueueEntry.id))
            .join(QueueEntry, QueueEntry.participant_id == Participant.id)
            .where(
                QueueEntry.session_id == session_id,
                QueueEntry.status.in_(QueueEntryStatus.non_terminal()),
            )
            .group_by(Participant.id, Participant.nickname, Participant.created_at)
            .order_by(Participant.created_at, Participant.id)
        )
        return [
            QueueParticipant(nickname=nickname, remaining_songs=count)
            for nickname, count in rows
        ]

    async def participant_details(
        self, session: AsyncSession, session_id: uuid.UUID
    ) -> list[HostParticipantDetailResponse]:
        """Host view of every participant and their queued playlist.

        Only non-terminal entries are shown: this is the actionable playlist the
        host can still run. Entries are ordered by round number then submission
        order; current-round entries carry their computed queue position.
        """
        await self.cleanup_absent_participants(session, session_id)
        active_entries = await self.get_active_entries(session, session_id)
        position_by_entry = {
            entry.id: index for index, entry in enumerate(active_entries, start=1)
        }

        participants = list(
            await session.scalars(
                select(Participant)
                .where(Participant.session_id == session_id)
                .order_by(Participant.created_at, Participant.id)
            )
        )
        entries = list(
            await session.scalars(
                select(QueueEntry)
                .join(Round, QueueEntry.round_id == Round.id)
                .where(
                    QueueEntry.session_id == session_id,
                    QueueEntry.status.in_(QueueEntryStatus.non_terminal()),
                )
                .order_by(Round.number, QueueEntry.created_at, QueueEntry.id)
            )
        )
        entries_by_participant: dict[uuid.UUID, list[HostParticipantEntryResponse]] = {
            participant.id: [] for participant in participants
        }
        for entry in entries:
            entries_by_participant.setdefault(entry.participant_id, []).append(
                HostParticipantEntryResponse(
                    id=entry.id,
                    round_number=entry.round.number,
                    position=position_by_entry.get(entry.id),
                    status=entry.status,
                    video_id=entry.youtube_video.youtube_video_id,
                    youtube_url=entry.youtube_video.youtube_url,
                    title=entry.youtube_video.title,
                    channel=entry.youtube_video.channel,
                    duration_seconds=entry.youtube_video.duration_seconds,
                    thumbnail_url=entry.youtube_video.thumbnail_url,
                    created_at=entry.created_at,
                )
            )
        return [
            HostParticipantDetailResponse(
                id=participant.id,
                session_id=participant.session_id,
                nickname=participant.nickname,
                created_at=participant.created_at,
                entries=entries_by_participant.get(participant.id, []),
            )
            for participant in participants
        ]

    async def reorder(
        self,
        session: AsyncSession,
        host_id: uuid.UUID,
        session_id: uuid.UUID,
        participant_names: list[str],
    ) -> None:
        """Set the host's manual order for the current round (queue revision).

        Per-round only: ``round_orders`` records the lineup for the active
        round; the next round (no rows) falls back to join order. Raises
        ``InvalidOrderError`` for unknown or duplicate nicknames and
        ``NoActiveRoundError`` when the queue is empty.
        """
        await session_service.get_for_host(session, host_id, session_id)
        karaoke_round = await self._active_round(session, session_id)
        if karaoke_round is None:
            raise NoActiveRoundError("the queue is empty — nothing to reorder")
        if len(set(participant_names)) != len(participant_names):
            raise InvalidOrderError("participant names must be unique")
        participants = await session.scalars(
            select(Participant).where(
                Participant.session_id == session_id,
                Participant.nickname.in_(participant_names),
            )
        )
        by_name = {participant.nickname: participant for participant in participants}
        missing = [name for name in participant_names if name not in by_name]
        if missing:
            raise InvalidOrderError(
                f"unknown participant(s): {', '.join(missing)}"
            )
        await session.execute(
            delete(RoundOrder).where(RoundOrder.round_id == karaoke_round.id)
        )
        session.add_all(
            [
                RoundOrder(
                    round_id=karaoke_round.id,
                    position=index,
                    participant_id=by_name[name].id,
                )
                for index, name in enumerate(participant_names)
            ]
        )
        await session.commit()

    async def reset_order(
        self, session: AsyncSession, host_id: uuid.UUID, session_id: uuid.UUID
    ) -> None:
        """Clear the host's reorder for the current round (back to join order)."""
        await session_service.get_for_host(session, host_id, session_id)
        karaoke_round = await self._active_round(session, session_id)
        if karaoke_round is not None:
            await session.execute(
                delete(RoundOrder).where(RoundOrder.round_id == karaoke_round.id)
            )
            await session.commit()

    async def session_summary(
        self, session: AsyncSession, session_id: uuid.UUID
    ) -> SessionSummaryResponse:
        """Host-facing round/session summary (M16, end-of-night wrap-up).

        Per participant: songs submitted (all), sung (``COMPLETED``), and still
        queued (non-terminal). Rounds played = ``rounds_completed``.
        """
        karaoke = await session_service.get_by_id(session, session_id)
        rows = await session.execute(
            select(
                Participant.nickname,
                func.count(QueueEntry.id),
                func.sum(
                    case(
                        (QueueEntry.status == QueueEntryStatus.COMPLETED, 1),
                        else_=0,
                    )
                ),
                func.sum(
                    case(
                        (
                            QueueEntry.status.in_(QueueEntryStatus.non_terminal()),
                            1,
                        ),
                        else_=0,
                    )
                ),
            )
            .join(QueueEntry, QueueEntry.participant_id == Participant.id)
            .where(QueueEntry.session_id == session_id)
            .group_by(Participant.id, Participant.nickname, Participant.created_at)
            .order_by(Participant.created_at, Participant.id)
        )
        participants = [
            SessionParticipantSummary(
                nickname=nickname,
                songs_submitted=int(submitted),
                songs_sung=int(sung if sung is not None else 0),
                songs_remaining=int(remaining if remaining is not None else 0),
            )
            for nickname, submitted, sung, remaining in rows
        ]
        return SessionSummaryResponse(
            session_id=karaoke.id,
            status=karaoke.status,
            active_round=await self.get_current_round_number(session, session_id),
            rounds_completed=await self.rounds_completed(session, session_id),
            participants=participants,
        )

    async def get_entry(
        self, session: AsyncSession, entry_id: uuid.UUID
    ) -> QueueEntry:
        """Return an entry (relationships loaded), or raise ``EntryNotFoundError``."""
        entry = await session.scalar(
            select(QueueEntry).where(QueueEntry.id == entry_id)
        )
        if entry is None:
            raise EntryNotFoundError(entry_id)
        return entry

    async def cancel(
        self,
        session: AsyncSession,
        participant: Participant,
        entry_id: uuid.UUID,
    ) -> QueueEntry:
        """Cancel the participant's own WAITING entry (B3).

        Works for any of the participant's own WAITING entries — the current
        round or a future round (M10.1). Returns the updated entry so callers
        can publish the realtime ``QueueUpdated`` event.
        """
        entry = await self.get_entry(session, entry_id)
        if (
            entry.session_id != participant.session_id
            or entry.participant_id != participant.id
        ):
            raise EntryNotFoundError(entry_id)
        if entry.status is not QueueEntryStatus.WAITING:
            raise EntryNotCancellableError(
                f"only WAITING entries can be cancelled, not {entry.status.value}"
            )
        entry.status = QueueEntryStatus.CANCELLED
        entry.ended_at = datetime.now(timezone.utc)
        await session.commit()
        return entry

    async def remove(
        self, session: AsyncSession, host_id: uuid.UUID, entry_id: uuid.UUID
    ) -> tuple[QueueEntry, bool]:
        """Remove any entry in one of the host's sessions (B4, M14).

        Returns ``(entry, was_singing)`` so the caller can advance playback when
        the current singer was removed (E6). Removing an entry that is already
        terminal is a no-op (E21 — e.g. the participant cancelled it first): the
        entry is returned unchanged.
        """
        entry = await self.get_entry(session, entry_id)
        try:
            await session_service.get_for_host(session, host_id, entry.session_id)
        except SessionNotFoundError as exc:
            raise EntryNotFoundError(entry_id) from exc
        if entry.status not in QueueEntryStatus.non_terminal():
            return entry, False
        was_singing = entry.status is QueueEntryStatus.SINGING
        entry.status = QueueEntryStatus.REMOVED
        entry.ended_at = datetime.now(timezone.utc)
        await session.commit()
        return entry, was_singing

    async def edit_video(
        self,
        session: AsyncSession,
        host_id: uuid.UUID,
        entry_id: uuid.UUID,
        data: YouTubeVideoData,
    ) -> QueueEntry:
        """Replace an entry's video in one of the host's sessions (B4).

        The entry keeps its participant and queue position; the metadata is
        re-fetched by the caller before this is invoked.
        """
        entry = await self.get_entry(session, entry_id)
        try:
            await session_service.get_for_host(session, host_id, entry.session_id)
        except SessionNotFoundError as exc:
            raise EntryNotFoundError(entry_id) from exc
        video = await self._get_or_create_video(session, data)
        entry.youtube_video_id = video.id
        await session.commit()
        # The FK column is already updated, but the selectin-loaded
        # ``youtube_video`` relationship is stale in the identity map; refresh
        # it so the returned entry reflects the new metadata.
        await session.refresh(entry, attribute_names=["youtube_video"])
        return entry

    # --- Round-robin internals --------------------------------------------------

    async def _join_index_map(
        self, session: AsyncSession, session_id: uuid.UUID
    ) -> dict[uuid.UUID, int]:
        """Map participant id -> join-order index (earliest join first)."""
        participants = await session.scalars(
            select(Participant)
            .where(Participant.session_id == session_id)
            .order_by(Participant.created_at, Participant.id)
        )
        return {participant.id: index for index, participant in enumerate(participants)}

    async def _round_order_map(
        self, session: AsyncSession, round_id: uuid.UUID
    ) -> dict[uuid.UUID, int] | None:
        """Map participant id -> reorder position for ``round_id``, or None."""
        rows = await session.scalars(
            select(RoundOrder)
            .where(RoundOrder.round_id == round_id)
            .order_by(RoundOrder.position)
        )
        mapping = {row.participant_id: row.position for row in rows}
        return mapping if mapping else None

    async def _active_round(
        self, session: AsyncSession, session_id: uuid.UUID
    ) -> Round | None:
        """Return the lowest-numbered round with a non-terminal entry, or None."""
        return await session.scalar(
            select(Round)
            .join(QueueEntry, QueueEntry.round_id == Round.id)
            .where(
                Round.session_id == session_id,
                QueueEntry.status.in_(QueueEntryStatus.non_terminal()),
            )
            .order_by(Round.number.asc())
            .limit(1)
        )

    async def _target_round(
        self, session: AsyncSession, participant: Participant
    ) -> Round:
        """Return the round a new song should be assigned to (B19/D43)."""
        active = await self._active_round(session, participant.session_id)
        if active is not None:
            has_in_active = await session.scalar(
                select(QueueEntry.id).where(
                    QueueEntry.round_id == active.id,
                    QueueEntry.participant_id == participant.id,
                    QueueEntry.status.in_(QueueEntryStatus.non_terminal()),
                )
            )
            if has_in_active is None:
                return active
            highest = await self._participant_highest_round(session, participant)
            return await self._get_or_create_round(
                session, participant.session_id, highest + 1
            )
        # Nothing is waiting anywhere. A fresh session's first songs belong to
        # round 1; after a round has ever held entries, a new song starts the
        # next numbered round (a fresh cycle).
        highest_with_entries = await session.scalar(
            select(func.max(Round.number))
            .join(QueueEntry, QueueEntry.round_id == Round.id)
            .where(Round.session_id == participant.session_id)
        )
        number = (
            1 if highest_with_entries is None else highest_with_entries + 1
        )
        return await self._get_or_create_round(
            session, participant.session_id, number
        )

    async def _participant_highest_round(
        self, session: AsyncSession, participant: Participant
    ) -> int:
        """Return the highest round number the participant has an entry in."""
        highest = await session.scalar(
            select(func.max(Round.number))
            .join(QueueEntry, QueueEntry.round_id == Round.id)
            .where(
                Round.session_id == participant.session_id,
                QueueEntry.participant_id == participant.id,
            )
        )
        return highest if highest is not None else 0

    async def _get_or_create_round(
        self, session: AsyncSession, session_id: uuid.UUID, number: int
    ) -> Round:
        """Return the round with ``number`` for the session, creating it if new.

        Round 1 is created with the session (D35); later rounds are created
        lazily when the first entry is assigned to them (D43). Handles the
        concurrent-insert race on the unique ``(session_id, number)``
        constraint by rolling back and re-selecting the winner (same pattern as
        ``_get_or_create_video``).
        """
        karaoke_round = await session.scalar(
            select(Round).where(
                Round.session_id == session_id, Round.number == number
            )
        )
        if karaoke_round is not None:
            return karaoke_round
        karaoke_round = Round(session_id=session_id, number=number)
        session.add(karaoke_round)
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            karaoke_round = await session.scalar(
                select(Round).where(
                    Round.session_id == session_id, Round.number == number
                )
            )
            if karaoke_round is None:
                raise  # pragma: no cover - unique constraint guarantees a winner
            return karaoke_round
        return karaoke_round

    async def _get_or_create_video(
        self, session: AsyncSession, data: YouTubeVideoData
    ) -> YouTubeVideo:
        """Return the metadata row for a video id, creating it if unknown.

        Handles the concurrent-insert race on the unique ``youtube_video_id``
        by rolling back and re-selecting the winner.
        """
        existing = await session.scalar(
            select(YouTubeVideo).where(
                YouTubeVideo.youtube_video_id == data.video_id
            )
        )
        if existing is not None:
            self._refresh_degraded_video(existing, data)
            return existing
        video = YouTubeVideo(
            youtube_video_id=data.video_id,
            youtube_url=data.youtube_url,
            title=data.title,
            channel=data.channel,
            duration_seconds=data.duration_seconds,
            thumbnail_url=data.thumbnail_url,
        )
        session.add(video)
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            existing = await session.scalar(
                select(YouTubeVideo).where(
                    YouTubeVideo.youtube_video_id == data.video_id
                )
            )
            if existing is None:
                raise  # pragma: no cover - unique constraint guarantees a winner
            self._refresh_degraded_video(existing, data)
            return existing
        return video

    def _refresh_degraded_video(
        self, existing: YouTubeVideo, data: YouTubeVideoData
    ) -> None:
        """Fill in a previously degraded oEmbed-only metadata row.

        Degraded rows have ``duration_seconds=0`` because oEmbed has no duration.
        If a later successful Data API fetch provides a real duration, keep the
        existing row/id (so duplicate entries still share metadata) and update
        display fields in-place. The caller's surrounding commit persists it.
        """
        if existing.duration_seconds != 0 or data.duration_seconds <= 0:
            return
        existing.youtube_url = data.youtube_url
        existing.title = data.title
        existing.channel = data.channel
        existing.duration_seconds = data.duration_seconds
        existing.thumbnail_url = data.thumbnail_url


queue_service = QueueService()
