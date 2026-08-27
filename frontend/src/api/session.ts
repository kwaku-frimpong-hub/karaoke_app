// API calls for the public join flow (backend M5).
import { apiRequest } from './client'
import type { JoinResult, JoinSession } from './types'

const BASE = '/api/v1/join'

export function lookupSession(joinCode: string): Promise<JoinSession> {
  return apiRequest<JoinSession>(`${BASE}/${joinCode}`)
}

export function joinSession(
  joinCode: string,
  nickname: string,
): Promise<JoinResult> {
  return apiRequest<JoinResult>(`${BASE}/${joinCode}/participants`, {
    method: 'POST',
    body: { nickname },
  })
}
