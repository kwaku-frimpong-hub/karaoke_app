// Host authentication screen (M3 backend): login or register, then land on the
// dashboard home. The host token is persisted (D38-style localStorage) so a
// reopened dashboard resumes without re-logging in (E11).
import { type FormEvent, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'

import { loginHost, registerHost } from '../../api/host'
import { loadHostIdentity, saveHostIdentity } from '../../lib/hostToken'

export default function HostAuthScreen() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Already logged in? Straight to the dashboard home.
  if (loadHostIdentity()) {
    return <Navigate to="/host" replace />
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'register') {
        await registerHost(email, password)
      }
      const result = await loginHost(email, password)
      saveHostIdentity({
        token: result.token,
        email: result.host.email,
        hostId: result.host.id,
      })
      navigate('/host', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not sign in')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="screen">
      <header className="auth-header">
        <h1>Friday Karaoke</h1>
        <p className="muted">
          {mode === 'login' ? 'Sign in to run your session' : 'Create a host account'}
        </p>
      </header>

      <form className="stack" onSubmit={handleSubmit}>
        <div className="field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
            autoFocus
          />
        </div>
        <div className="field">
          <label htmlFor="password">
            {mode === 'register' ? 'Password (min 8 characters)' : 'Password'}
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
          />
        </div>
        <button type="submit" disabled={busy || email.trim() === '' || password === ''}>
          {busy ? 'Signing in…' : mode === 'register' ? 'Create account' : 'Sign in'}
        </button>
        {error ? <p className="error-text">{error}</p> : null}
      </form>

      <button
        className="ghost"
        onClick={() => {
          setMode(mode === 'login' ? 'register' : 'login')
          setError(null)
        }}
      >
        {mode === 'login'
          ? 'No account yet? Create one'
          : 'Already have an account? Sign in'}
      </button>
    </div>
  )
}
