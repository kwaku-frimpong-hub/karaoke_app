// Song submission screen (PRODUCT_SPEC §6.3-6.4): paste a YouTube URL, review
// the metadata preview, then add it to the queue (backend M6/M7).
import { type FormEvent, useState } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'

import { fetchPreview, submitSong } from '../../api/entries'
import type { SongPreview, SongSubmitResult } from '../../api/types'
import { formatDuration } from '../../lib/format'
import { loadIdentity } from '../../lib/token'

export default function SubmitSongScreen() {
  const { joinCode = '' } = useParams()
  const identity = loadIdentity()

  const [url, setUrl] = useState('')
  const [preview, setPreview] = useState<SongPreview | null>(null)
  const [result, setResult] = useState<SongSubmitResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (
    !identity ||
    identity.joinCode.toLowerCase() !== joinCode.toLowerCase()
  ) {
    return <Navigate to={`/join/${joinCode}`} replace />
  }
  // Narrowed alias so the closures below see a non-null identity.
  const me = identity

  async function handlePreview(event: FormEvent) {
    event.preventDefault()
    if (url.trim() === '') return
    setLoading(true)
    setError(null)
    setPreview(null)
    try {
      const data = await fetchPreview(me.sessionId, me.token, url.trim())
      setPreview(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load this video')
    } finally {
      setLoading(false)
    }
  }

  async function handleAdd() {
    if (!preview) return
    setLoading(true)
    setError(null)
    try {
      const data = await submitSong(me.sessionId, me.token, preview.youtube_url)
      setResult(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add the song')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="screen">
      <header className="topbar">
        <Link to={`/join/${joinCode}/queue`}>&larr; Queue</Link>
      </header>
      <h1>Add a song</h1>

      <form className="stack" onSubmit={handlePreview}>
        <div className="field">
          <label htmlFor="youtube-url">YouTube link</label>
          <input
            id="youtube-url"
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="Paste a YouTube link"
            required
          />
        </div>
        <button type="submit" disabled={loading || url.trim() === ''}>
          {loading && !preview ? 'Checking…' : 'Preview'}
        </button>
      </form>

      {error ? <p className="error-text">{error}</p> : null}

      {preview && !result ? (
        <div className="card">
          {preview.thumbnail_url ? (
            <img src={preview.thumbnail_url} alt="" className="thumb" />
          ) : null}
          <h2>{preview.title}</h2>
          <p className="muted">
            {preview.channel} &middot; {formatDuration(preview.duration_seconds)}
          </p>
          {preview.is_long && preview.warning ? (
            <p className="warn-text">{preview.warning}</p>
          ) : null}
          <div className="row">
            <button onClick={handleAdd} disabled={loading}>
              {loading ? 'Adding…' : 'Add to Queue'}
            </button>
            <button className="ghost" onClick={() => setPreview(null)}>
              Try Another URL
            </button>
          </div>
        </div>
      ) : null}

      {result ? (
        <div className="card success">
          <h2>Added!</h2>
          <p>
            &ldquo;{result.entry.title}&rdquo; is position{' '}
            <strong>{result.entry.position ?? '—'}</strong> in the queue.
          </p>
          {result.notice ? <p className="warn-text">{result.notice}</p> : null}
          <div className="row">
            <Link className="button-link" to={`/join/${joinCode}/queue`}>
              View Queue
            </Link>
            <button
              className="ghost"
              onClick={() => {
                setResult(null)
                setPreview(null)
                setUrl('')
              }}
            >
              Add Another
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}
