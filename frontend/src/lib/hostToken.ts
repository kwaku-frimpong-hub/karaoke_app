// Persistence of the host identity (M3 bearer token + profile).
// Stored in localStorage so reopening the dashboard resumes the session list
// without re-logging in (E11); the backend remains the source of truth for all
// state. Mirrors the participant identity approach (D38).

export interface HostIdentity {
  token: string
  email: string
  hostId: string
}

const STORAGE_KEY = 'karaoke.host'

export function loadHostIdentity(): HostIdentity | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as HostIdentity
    if (!parsed.token || !parsed.hostId) return null
    return parsed
  } catch {
    return null
  }
}

export function saveHostIdentity(identity: HostIdentity): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(identity))
}

export function clearHostIdentity(): void {
  localStorage.removeItem(STORAGE_KEY)
}
