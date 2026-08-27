// Persistence of the participant identity (M5 token + session binding).
// Stored in localStorage so a refresh does not lose the join (E8); the backend
// remains the source of truth for all state.

export interface ParticipantIdentity {
  token: string
  sessionId: string
  sessionName: string
  joinCode: string
  nickname: string
}

const STORAGE_KEY = 'karaoke.participant'

export function loadIdentity(): ParticipantIdentity | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as ParticipantIdentity
    if (!parsed.token || !parsed.sessionId) return null
    return parsed
  } catch {
    return null
  }
}

export function saveIdentity(identity: ParticipantIdentity): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(identity))
}

export function clearIdentity(): void {
  localStorage.removeItem(STORAGE_KEY)
}
