// API calls for songs and the queue (backend M6/M7).
import { apiRequest } from './client'
import type { QueueEntry, QueueSnapshot, SongPreview, SongSubmitResult } from './types'

export function fetchPreview(
  sessionId: string,
  token: string,
  youtubeUrl: string,
): Promise<SongPreview> {
  return apiRequest<SongPreview>(
    `/api/v1/sessions/${sessionId}/entries/preview`,
    { method: 'POST', body: { youtube_url: youtubeUrl }, token },
  )
}

export function submitSong(
  sessionId: string,
  token: string,
  youtubeUrl: string,
): Promise<SongSubmitResult> {
  return apiRequest<SongSubmitResult>(`/api/v1/sessions/${sessionId}/entries`, {
    method: 'POST',
    body: { youtube_url: youtubeUrl },
    token,
  })
}

export function fetchQueueSnapshot(sessionId: string): Promise<QueueSnapshot> {
  return apiRequest<QueueSnapshot>(`/api/v1/sessions/${sessionId}/entries`)
}

/** The participant's own queued songs: the current-round entry (with position)
 *  followed by upcoming songs for later rounds (M10.1, position null). */
export function fetchMyEntries(
  sessionId: string,
  token: string,
): Promise<QueueEntry[]> {
  return apiRequest<QueueEntry[]>(`/api/v1/sessions/${sessionId}/entries/mine`, {
    token,
  })
}

/** Delete the participant + all their songs (leave the night early). Their
 *  nickname is freed and their token dies; the queue updates for everyone. */
export function leaveSession(sessionId: string, token: string): Promise<void> {
  return apiRequest<void>(`/api/v1/sessions/${sessionId}/leave`, {
    method: 'POST',
    token,
  })
}

export function cancelEntry(entryId: string, token: string): Promise<void> {
  return apiRequest<void>(`/api/v1/entries/${entryId}`, {
    method: 'DELETE',
    token,
  })
}

// --- Host moderation actions (M7, used by the M9 dashboard) ---

/** Host removes any queue entry (B4). Same DELETE path as participant cancel (D37). */
export function removeEntry(entryId: string, token: string): Promise<void> {
  return apiRequest<void>(`/api/v1/entries/${entryId}`, {
    method: 'DELETE',
    token,
  })
}

/** Host replaces an entry's YouTube URL; backend re-validates + re-fetches (E7). */
export function editEntryVideo(
  entryId: string,
  token: string,
  youtubeUrl: string,
): Promise<QueueEntry> {
  return apiRequest<QueueEntry>(`/api/v1/entries/${entryId}/video`, {
    method: 'PATCH',
    body: { youtube_url: youtubeUrl },
    token,
  })
}
