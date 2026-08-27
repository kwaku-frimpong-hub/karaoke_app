// Host dashboard home (M9): create a new session or pick an existing one.
// The session list comes from the backend (GET /api/v1/sessions, M9) so the
// host can re-sync after reopening the dashboard (E11). The frontend never
// owns session state — it renders what the backend returns.
import { type FormEvent, useCallback, useEffect, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { createSession, listSessions, logoutHost } from '../../api/host'
import type { Session } from '../../api/types'
import { clearHostIdentity, loadHostIdentity } from '../../lib/hostToken'
import { statusLabel } from '../../lib/session'

export default function HostHomeScreen() {
  const navigate = useNavigate()
  const [identity] = useState(loadHostIdentity)

  const [sessions, setSessions] = useState<Session[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [creating, setCreating] = useState(false)

  const refresh = useCallback(async () => {
    if (!identity) return
    try {
      setSessions(await listSessions(identity.token))
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load sessions')
    }
  }, [identity])

  useEffect(() => {
    void refresh()
  }, [refresh])

  if (!identity) {
    return <Navigate to="/host/login" replace />
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault()
    if (!identity) return
    setCreating(true)
    setError(null)
    try {
      const created = await createSession(identity.token, name)
      navigate(`/host/sessions/${created.id}`, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create the session')
    } finally {
      setCreating(false)
    }
  }

  async function handleLogout() {
    if (!identity) return
    try {
      await logoutHost(identity.token)
    } catch {
      // Logout is best-effort: the token is also cleared locally.
    }
    clearHostIdentity()
    navigate('/host/login', { replace: true })
  }

  return (
    <div className="screen">
      <header className="topbar">
        <span className="session-name">Host dashboard</span>
        <span className="muted">{identity.email}</span>
      </header>

      <form className="card stack" onSubmit={handleCreate}>
        <h2>New session</h2>
        <div className="field">
          <label htmlFor="session-name">Session name</label>
          <input
            id="session-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Defaults to Friday Karaoke - today"
            maxLength={100}
          />
        </div>
        <button type="submit" disabled={creating}>
          {creating ? 'Creating…' : 'Create session'}
        </button>
        {error ? <p className="error-text">{error}</p> : null}
      </form>

      <section>
        <h2>Your sessions</h2>
        {sessions === null ? (
          <p className="muted">Loading…</p>
        ) : sessions.length === 0 ? (
          <p className="muted">No sessions yet — create your first one above.</p>
        ) : (
          <ol className="queue-list home-list">
            {sessions.map((session) => (
              <li key={session.id}>
                <div className="entry-main">
                  <strong>{session.name}</strong>
                  <span className="muted">
                    Code {session.join_code} &middot; {statusLabel(session.status)}
                  </span>
                </div>
                <Link className="home-open button-link" to={`/host/sessions/${session.id}`}>
                  Open
                </Link>
              </li>
            ))}
          </ol>
        )}
      </section>

      <button className="ghost" onClick={() => void handleLogout()}>
        Log out
      </button>
    </div>
  )
}
