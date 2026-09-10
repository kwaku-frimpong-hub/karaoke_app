// Best-effort optimistic queue/playback predictions. The backend remains the
// source of truth; these helpers only make the UI react instantly until the next
// authoritative REST/WebSocket snapshot reconciles the state.
import type { QueueEntry, QueueSnapshot, SessionStatus } from '../api/types'

export type PlaybackAction =
  | 'start'
  | 'end'
  | 'skip'
  | 'finish'
  | 'advance'
  | 'pause'
  | 'resume'

function deadline(now: Date, seconds: number): string {
  return new Date(now.getTime() + seconds * 1000).toISOString()
}

function withPositions(queue: QueueEntry[]): QueueEntry[] {
  return queue.map((entry, index) => ({ ...entry, position: index + 1 }))
}

function adjustParticipantCount(
  snapshot: QueueSnapshot,
  participantName: string,
  delta: number,
): QueueSnapshot['participants'] {
  return snapshot.participants
    .map((participant) =>
      participant.nickname === participantName
        ? { ...participant, remaining_songs: participant.remaining_songs + delta }
        : participant,
    )
    .filter((participant) => participant.remaining_songs > 0)
}

function promoteFront(queue: QueueEntry[]): QueueEntry[] {
  if (queue.length === 0) return queue
  return queue.map((entry, index) => ({
    ...entry,
    status: index === 0 ? 'NEXT' : entry.status === 'NEXT' ? 'WAITING' : entry.status,
  }))
}

function beginTransition(
  snapshot: QueueSnapshot,
  queue: QueueEntry[],
  now: Date,
  skipCooldown: boolean,
): QueueSnapshot {
  if (queue.length === 0) {
    return {
      ...snapshot,
      queue,
      playback_state: 'IDLE',
      transition_until: null,
      transition_remaining_seconds: null,
    }
  }
  if (skipCooldown || snapshot.cooldown_seconds === 0) {
    return {
      ...snapshot,
      queue,
      playback_state: 'COUNTDOWN',
      transition_until: deadline(now, snapshot.countdown_seconds),
      transition_remaining_seconds: snapshot.countdown_seconds,
    }
  }
  return {
    ...snapshot,
    queue,
    playback_state: 'COOLDOWN',
    transition_until: deadline(now, snapshot.cooldown_seconds),
    transition_remaining_seconds: snapshot.cooldown_seconds,
  }
}

export function predictPlaybackAction(
  snapshot: QueueSnapshot,
  action: PlaybackAction,
  now: Date = new Date(),
): QueueSnapshot {
  if (action === 'pause') return predictSessionStatus(snapshot, 'PAUSED')
  if (action === 'resume') return predictSessionStatus(snapshot, 'ACTIVE')

  if (action === 'start') {
    if (snapshot.queue.length === 0) return snapshot
    return {
      ...snapshot,
      queue: withPositions(snapshot.queue.map((entry, index) => ({
        ...entry,
        status: index === 0 ? 'SINGING' : entry.status === 'NEXT' ? 'WAITING' : entry.status,
      }))),
      playback_state: 'PLAYING',
      transition_until: null,
      transition_remaining_seconds: null,
    }
  }

  if (action === 'advance') {
    if (snapshot.playback_state === 'COOLDOWN') {
      return {
        ...snapshot,
        playback_state: 'COUNTDOWN',
        transition_until: deadline(now, snapshot.countdown_seconds),
        transition_remaining_seconds: snapshot.countdown_seconds,
      }
    }
    if (snapshot.playback_state === 'COUNTDOWN') {
      if (snapshot.queue.length === 0) {
        return {
          ...snapshot,
          playback_state: 'IDLE',
          transition_until: null,
          transition_remaining_seconds: null,
        }
      }
      return {
        ...snapshot,
        queue: withPositions(snapshot.queue.map((entry, index) => ({
          ...entry,
          status: index === 0 ? 'SINGING' : entry.status === 'NEXT' ? 'WAITING' : entry.status,
        }))),
        playback_state: 'PLAYING',
        transition_until: null,
        transition_remaining_seconds: null,
      }
    }
    return snapshot
  }

  const currentIndex = snapshot.queue.findIndex((entry) => entry.status === 'SINGING')
  if (currentIndex < 0) return snapshot
  const current = snapshot.queue[currentIndex]

  if (action === 'skip') {
    const withoutCurrent = snapshot.queue.filter((entry) => entry.id !== current.id)
    const movedQueue = withoutCurrent.length === 0
      ? []
      : [...withoutCurrent, { ...current, status: 'WAITING' as const }]
    const queue = withPositions(promoteFront(movedQueue))
    return beginTransition(snapshot, queue, now, true)
  }

  const queue = withPositions(promoteFront(snapshot.queue.filter((entry) => entry.id !== current.id)))
  return beginTransition(
    {
      ...snapshot,
      participants: adjustParticipantCount(snapshot, current.participant_name, -1),
    },
    queue,
    now,
    action === 'finish',
  )
}

export function predictSessionStatus(
  snapshot: QueueSnapshot,
  status: SessionStatus,
): QueueSnapshot {
  const cancelsTransition = status === 'PAUSED'
    && (snapshot.playback_state === 'COOLDOWN' || snapshot.playback_state === 'COUNTDOWN')
  return {
    ...snapshot,
    status,
    playback_state: cancelsTransition ? 'IDLE' : snapshot.playback_state,
    transition_until: cancelsTransition ? null : snapshot.transition_until,
    transition_remaining_seconds: cancelsTransition ? null : snapshot.transition_remaining_seconds,
  }
}

export function predictRemoveEntry(snapshot: QueueSnapshot, entryId: string): QueueSnapshot {
  const removed = snapshot.queue.find((entry) => entry.id === entryId)
  if (!removed) return snapshot
  const remaining = snapshot.queue.filter((entry) => entry.id !== entryId)
  const participants = adjustParticipantCount(snapshot, removed.participant_name, -1)
  if (removed.status === 'SINGING') {
    return beginTransition(
      { ...snapshot, participants },
      withPositions(promoteFront(remaining)),
      new Date(),
      true,
    )
  }
  return { ...snapshot, participants, queue: withPositions(remaining) }
}

export function predictReorder(snapshot: QueueSnapshot, names: string[]): QueueSnapshot {
  const order = new Map(names.map((name, index) => [name, index]))
  const queue = [...snapshot.queue].sort((left, right) => {
    const leftOrder = order.get(left.participant_name) ?? names.length
    const rightOrder = order.get(right.participant_name) ?? names.length
    return leftOrder - rightOrder
  })
  return { ...snapshot, queue: withPositions(queue) }
}

export function predictEditEntry(
  snapshot: QueueSnapshot,
  entryId: string,
  youtubeUrl: string,
): QueueSnapshot {
  return {
    ...snapshot,
    queue: snapshot.queue.map((entry) =>
      entry.id === entryId
        ? {
            ...entry,
            youtube_url: youtubeUrl,
            title: 'Song syncing…',
            channel: 'Metadata updating',
            duration_seconds: 0,
            thumbnail_url: '',
          }
        : entry,
    ),
  }
}

export function withUpdatedEntry(snapshot: QueueSnapshot, updated: QueueEntry): QueueSnapshot {
  return {
    ...snapshot,
    queue: snapshot.queue.map((entry) => (entry.id === updated.id ? updated : entry)),
  }
}
