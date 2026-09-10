// API calls for the host dashboard (backend M3 host auth + M4/M5 sessions).
import { apiRequest, apiRequestText } from './client'
import type {
  HostParticipantDetail,
  HostLoginResult,
  HostProfile,
  Participant,
  QueueSnapshot,
  Session,
  SessionSummary,
  SongSubmitResult,
} from './types'

const AUTH_BASE = '/api/v1/auth/host'
const SESSIONS_BASE = '/api/v1/sessions'

export function registerHost(
  email: string,
  password: string,
): Promise<HostProfile> {
  return apiRequest<HostProfile>(`${AUTH_BASE}/register`, {
    method: 'POST',
    body: { email, password },
  })
}

export function loginHost(email: string, password: string): Promise<HostLoginResult> {
  return apiRequest<HostLoginResult>(`${AUTH_BASE}/login`, {
    method: 'POST',
    body: { email, password },
  })
}

export function logoutHost(token: string): Promise<void> {
  return apiRequest<void>(`${AUTH_BASE}/logout`, { method: 'POST', token })
}

export function listSessions(token: string): Promise<Session[]> {
  return apiRequest<Session[]>(SESSIONS_BASE, { token })
}

export function createSession(token: string, name?: string): Promise<Session> {
  return apiRequest<Session>(SESSIONS_BASE, {
    method: 'POST',
    body: name !== undefined && name.trim() !== '' ? { name: name.trim() } : {},
    token,
  })
}

export function fetchSession(token: string, sessionId: string): Promise<Session> {
  return apiRequest<Session>(`${SESSIONS_BASE}/${sessionId}`, { token })
}

export function fetchHostParticipants(
  token: string,
  sessionId: string,
): Promise<HostParticipantDetail[]> {
  return apiRequest<HostParticipantDetail[]>(
    `${SESSIONS_BASE}/${sessionId}/participants`,
    { token },
  )
}

export function createHostParticipant(
  token: string,
  sessionId: string,
  nickname: string,
): Promise<Participant> {
  return apiRequest<Participant>(`${SESSIONS_BASE}/${sessionId}/participants`, {
    method: 'POST',
    body: { nickname },
    token,
  })
}

export function addHostParticipantSong(
  token: string,
  sessionId: string,
  participantId: string,
  youtubeUrl: string,
): Promise<SongSubmitResult> {
  return apiRequest<SongSubmitResult>(
    `${SESSIONS_BASE}/${sessionId}/participants/${participantId}/entries`,
    {
      method: 'POST',
      body: { youtube_url: youtubeUrl },
      token,
    },
  )
}

/** Host-facing round/session summary (M16): rounds played + per-participant
 *  song counts for the dashboard and the end-of-night wrap-up. */
export function fetchSessionSummary(
  token: string,
  sessionId: string,
): Promise<SessionSummary> {
  return apiRequest<SessionSummary>(`${SESSIONS_BASE}/${sessionId}/summary`, {
    token,
  })
}

/** Set the host's manual order for the current round (per-round; the next
 *  round resets to join order). Returns the updated snapshot. */
export function reorderSession(
  token: string,
  sessionId: string,
  participantNames: string[],
): Promise<QueueSnapshot> {
  return apiRequest<QueueSnapshot>(`${SESSIONS_BASE}/${sessionId}/order`, {
    method: 'PATCH',
    body: { participant_names: participantNames },
    token,
  })
}

/** Clear the current round's reorder (back to join order). */
export function resetSessionOrder(
  token: string,
  sessionId: string,
): Promise<QueueSnapshot> {
  return apiRequest<QueueSnapshot>(`${SESSIONS_BASE}/${sessionId}/order`, {
    method: 'DELETE',
    token,
  })
}

export function startSession(token: string, sessionId: string): Promise<Session> {
  return apiRequest<Session>(`${SESSIONS_BASE}/${sessionId}/start`, {
    method: 'POST',
    token,
  })
}

export function endSession(token: string, sessionId: string): Promise<Session> {
  return apiRequest<Session>(`${SESSIONS_BASE}/${sessionId}/end`, {
    method: 'POST',
    token,
  })
}

/** Fetch the session's join QR code (SVG source, decision D32). */
export function fetchSessionQr(token: string, sessionId: string): Promise<string> {
  return apiRequestText(`${SESSIONS_BASE}/${sessionId}/qr`, { token })
}

// --- Playback controls (M11) ---

/** Start playing the front of the queue (returns the authoritative snapshot). */
export function startPlayback(
  token: string,
  sessionId: string,
): Promise<QueueSnapshot> {
  return apiRequest<QueueSnapshot>(`${SESSIONS_BASE}/${sessionId}/play/start`, {
    method: 'POST',
    token,
  })
}

/** Skip the current singer (SKIPPED) and begin the countdown (D20/M13). */
export function skipPlayback(
  token: string,
  sessionId: string,
): Promise<QueueSnapshot> {
  return apiRequest<QueueSnapshot>(`${SESSIONS_BASE}/${sessionId}/play/skip`, {
    method: 'POST',
    token,
  })
}

/** The host player reports the current video ended naturally (M13): the entry
 *  becomes COMPLETED and the cooldown → countdown → auto-start begins. */
export function endPlayback(
  token: string,
  sessionId: string,
): Promise<QueueSnapshot> {
  return apiRequest<QueueSnapshot>(`${SESSIONS_BASE}/${sessionId}/play/end`, {
    method: 'POST',
    token,
  })
}

/** Finish the current singer (COMPLETED) and begin the countdown (D20/M13). */
export function finishPlayback(
  token: string,
  sessionId: string,
): Promise<QueueSnapshot> {
  return apiRequest<QueueSnapshot>(`${SESSIONS_BASE}/${sessionId}/play/finish`, {
    method: 'POST',
    token,
  })
}

/** Progress an automatic transition whose phase deadline passed (M13). */
export function advancePlayback(
  token: string,
  sessionId: string,
): Promise<QueueSnapshot> {
  return apiRequest<QueueSnapshot>(`${SESSIONS_BASE}/${sessionId}/play/advance`, {
    method: 'POST',
    token,
  })
}

/** Pause automatic progression (ACTIVE -> PAUSED). */
export function pausePlayback(
  token: string,
  sessionId: string,
): Promise<QueueSnapshot> {
  return apiRequest<QueueSnapshot>(`${SESSIONS_BASE}/${sessionId}/play/pause`, {
    method: 'POST',
    token,
  })
}

/** Resume progression (PAUSED -> ACTIVE). */
export function resumePlayback(
  token: string,
  sessionId: string,
): Promise<QueueSnapshot> {
  return apiRequest<QueueSnapshot>(`${SESSIONS_BASE}/${sessionId}/play/resume`, {
    method: 'POST',
    token,
  })
}
