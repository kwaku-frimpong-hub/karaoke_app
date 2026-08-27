// Typed WebSocket client for the M10 realtime channel (delivery only, D5).
//
// The backend broadcasts typed domain events to every subscriber of a session.
// Events are NOT authoritative state: after a reconnect the client must
// re-fetch the authoritative snapshot from the REST API. These types mirror
// the backend Pydantic event models in backend/app/schemas/realtime.py.

import type { QueueSnapshot, SessionStatus } from '../api/types'

export interface QueueUpdatedEvent {
  type: 'QueueUpdated'
  session_id: string
  snapshot: QueueSnapshot
}

export interface ParticipantJoinedEvent {
  type: 'ParticipantJoined'
  session_id: string
  nickname: string
}

export interface SessionUpdatedEvent {
  type: 'SessionUpdated'
  session_id: string
  status: SessionStatus
}

export interface SingerStartedEvent {
  type: 'SingerStarted'
  session_id: string
  entry_id: string
  participant_name: string
  title: string
}

export interface SingerFinishedEvent {
  type: 'SingerFinished'
  session_id: string
  entry_id: string
}

export interface SingerSkippedEvent {
  type: 'SingerSkipped'
  session_id: string
  entry_id: string
}

export interface NextSingerNotifiedEvent {
  type: 'NextSingerNotified'
  session_id: string
  entry_id: string
  participant_name: string
  title: string
  channel: string
  phase: 'next' | 'countdown'
}

export type RealtimeEvent =
  | QueueUpdatedEvent
  | ParticipantJoinedEvent
  | SessionUpdatedEvent
  | SingerStartedEvent
  | SingerFinishedEvent
  | SingerSkippedEvent
  | NextSingerNotifiedEvent

/** Build the WebSocket URL for a session, carrying the bearer token as a
 *  query parameter (the browser WebSocket API cannot set request headers). */
export function realtimeWsUrl(sessionId: string, token: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/api/v1/sessions/${sessionId}/ws?token=${encodeURIComponent(token)}`
}

/** Parse a raw WebSocket frame into a typed event, or null when malformed. */
export function parseRealtimeEvent(raw: string): RealtimeEvent | null {
  try {
    const parsed = JSON.parse(raw) as RealtimeEvent
    const known = [
      'QueueUpdated',
      'ParticipantJoined',
      'SessionUpdated',
      'SingerStarted',
      'SingerFinished',
      'SingerSkipped',
      'NextSingerNotified',
    ]
    if (!known.includes(parsed.type)) return null
    return parsed
  } catch {
    return null
  }
}
