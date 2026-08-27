// Participant join screen (PRODUCT_SPEC §7.1): reach the session behind a join
// code, enter a nickname, and receive the opaque participant token (M5).
import { type FormEvent, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { joinSession, lookupSession } from '../../api/session'
import type { JoinSession } from '../../api/types'
import { loadIdentity, saveIdentity } from '../../lib/token'

export default function JoinScreen() {
  const { joinCode = '' } = useParams()
  const navigate = useNavigate()

  const [session, setSession] = useState<JoinSession | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [nickname, setNickname] = useState('')
  const [joining, setJoining] = useState(false)

  useEffect(() => {
    // Already joined this session? Go straight to the queue (E8 refresh).
    const identity = loadIdentity()
    if (
      identity &&
      identity.joinCode.toLowerCase() === joinCode.toLowerCase()
    ) {
      navigate(`/join/${joinCode}/queue`, { replace: true })
      return
    }

    let cancelled = false
    setLoading(true)
    lookupSession(joinCode)
      .then((found) => {
        if (cancelled) return
        setSession(found)
        setError(null)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not find this session')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [joinCode, navigate])

  async function handleJoin(event: FormEvent) {
    event.preventDefault()
    if (!session) return
    setJoining(true)
    setError(null)
    try {
      const result = await joinSession(joinCode, nickname)
      saveIdentity({
        token: result.token,
        sessionId: result.session.id,
        sessionName: result.session.name,
        joinCode,
        nickname: result.participant.nickname,
      })
      navigate(`/join/${joinCode}/queue`, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not join')
    } finally {
      setJoining(false)
    }
  }

  if (loading) {
    return (
      <div className="screen">
        <p className="muted">Loading session…</p>
      </div>
    )
  }

  if (error && !session) {
    return (
      <div className="screen">
        <h1>Friday Karaoke</h1>
        <p className="error-text">{error}</p>
      </div>
    )
  }

  if (!session) {
    return null
  }

  if (session.status === 'ENDED') {
    return (
      <div className="screen">
        <h1>{session.name}</h1>
        <p className="error-text">This karaoke night has ended.</p>
      </div>
    )
  }

  return (
    <div className="screen">
      <h1>{session.name}</h1>
      <p className="muted">Enter your nickname to join the queue.</p>
      <form className="stack" onSubmit={handleJoin}>
        <div className="field">
          <label htmlFor="nickname">Nickname</label>
          <input
            id="nickname"
            type="text"
            value={nickname}
            onChange={(e) => setNickname(e.target.value)}
            placeholder="How you want to be called"
            maxLength={20}
            required
            autoFocus
          />
        </div>
        <button type="submit" disabled={joining || nickname.trim() === ''}>
          {joining ? 'Joining…' : 'Join'}
        </button>
        {error ? <p className="error-text">{error}</p> : null}
      </form>
    </div>
  )
}
