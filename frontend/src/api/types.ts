// Types mirroring the backend Pydantic API contracts (docs/API_CONTRACT.md).
// The backend is the single source of truth: these are the shapes the backend
// returns, never client-owned state.

export type SessionStatus =
  | 'CREATED'
  | 'ACTIVE'
  | 'PAUSED'
  | 'ENDED'

export type PlaybackState =
  | 'IDLE'
  | 'PREPARING'
  | 'COUNTDOWN'
  | 'PLAYING'
  | 'COOLDOWN'
  | 'FINISHED'
  | 'SKIPPED'

export type QueueEntryStatus =
  | 'WAITING'
  | 'NEXT'
  | 'SINGING'
  | 'COMPLETED'
  | 'SKIPPED'
  | 'CANCELLED'
  | 'REMOVED'

export interface JoinSession {
  id: string
  name: string
  status: SessionStatus
}

export interface Participant {
  id: string
  session_id: string
  nickname: string
  created_at: string
}

export interface HostParticipantEntry {
  id: string
  round_number: number
  position: number | null
  status: QueueEntryStatus
  video_id: string
  youtube_url: string
  title: string
  channel: string
  duration_seconds: number
  thumbnail_url: string
  created_at: string
}

export interface HostParticipantDetail {
  id: string
  session_id: string
  nickname: string
  created_at: string
  entries: HostParticipantEntry[]
}

export interface JoinResult {
  token: string
  token_type: 'bearer'
  session: JoinSession
  participant: Participant
}

export interface SongPreview {
  youtube_url: string
  video_id: string
  title: string
  channel: string
  duration_seconds: number
  thumbnail_url: string
  is_long: boolean
  warning: string | null
}

export interface QueueEntry {
  id: string
  participant_name: string
  status: QueueEntryStatus
  video_id: string
  youtube_url: string
  title: string
  channel: string
  duration_seconds: number
  thumbnail_url: string
  position: number | null
  created_at: string
}

export interface QueueParticipant {
  nickname: string
  remaining_songs: number
}

export interface QueueSnapshot {
  session_id: string
  status: SessionStatus
  round_number: number
  rounds_completed: number
  playback_state: PlaybackState
  transition_until: string | null
  transition_remaining_seconds: number | null
  cooldown_seconds: number
  countdown_seconds: number
  participants: QueueParticipant[]
  queue: QueueEntry[]
}

export interface SessionParticipantSummary {
  nickname: string
  songs_submitted: number
  songs_sung: number
  songs_remaining: number
}

export interface SessionSummary {
  session_id: string
  status: SessionStatus
  active_round: number
  rounds_completed: number
  participants: SessionParticipantSummary[]
}

export interface SongSubmitResult {
  entry: QueueEntry
  duplicate: boolean
  notice: string | null
}

// --- Host-facing types (M9 dashboard) ---

export interface HostProfile {
  id: string
  email: string
  created_at: string
}

export interface HostLoginResult {
  token: string
  token_type: 'bearer'
  host: HostProfile
}

export interface Session {
  id: string
  name: string
  join_code: string
  join_url: string
  status: SessionStatus
  created_at: string
  started_at: string | null
  ended_at: string | null
}
