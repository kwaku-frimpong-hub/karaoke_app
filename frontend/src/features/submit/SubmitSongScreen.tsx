// Song submission screen (PRODUCT_SPEC §6.3-6.4): paste a YouTube URL, review
// instant keyless metadata, then optimistically add it to the queue.
import { type FormEvent, useState } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'

import type { SongSubmitResult } from '../../api/types'
import { formatDuration } from '../../lib/format'
import { loadIdentity } from '../../lib/token'
import { type ClientVideoMetadata, fetchOEmbedMetadata } from '../../lib/youtube'
import { useQueueStore } from '../../queue/context'

interface InstantSuccess {
  title: string
  syncing: boolean
  notice: string | null
}

function durationLabel(durationSeconds: number | null): string {
  return durationSeconds === null || durationSeconds === 0
    ? 'duration resolving'
    : formatDuration(durationSeconds)
}

export default function SubmitSongScreen() {
  const { joinCode = '' } = useParams()
  const identity = loadIdentity()
  const queueStore = useQueueStore()

  const [url, setUrl] = useState('')
  const [preview, setPreview] = useState<ClientVideoMetadata | null>(null)
  const [result, setResult] = useState<SongSubmitResult | null>(null)
  const [instantSuccess, setInstantSuccess] = useState<InstantSuccess | null>(null)
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
    setResult(null)
    setInstantSuccess(null)
    try {
      const data = await fetchOEmbedMetadata(url.trim())
      setPreview(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load this video')
    } finally {
      setLoading(false)
    }
  }

  async function handleAdd() {
    if (!preview) return
    setError(null)
    setResult(null)
    setInstantSuccess({ title: preview.title, syncing: true, notice: null })
    try {
      const data = await queueStore.addParticipantSong({
        sessionId: me.sessionId,
        token: me.token,
        participantName: me.nickname,
        metadata: preview,
      })
      setResult(data)
      setInstantSuccess({
        title: data.entry.title,
        syncing: false,
        notice: data.notice,
      })
    } catch (err) {
      setInstantSuccess(null)
      setError(err instanceof Error ? err.message : 'Could not add the song')
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
          {loading ? 'Loading song…' : 'Show song'}
        </button>
      </form>

      {error ? <p className="error-text">{error}</p> : null}

      {preview && !result ? (
        <div className="card">
          {preview.thumbnailUrl ? (
            <img src={preview.thumbnailUrl} alt="" className="thumb" />
          ) : null}
          <h2>{preview.title}</h2>
          <p className="muted">
            {preview.channel || 'YouTube'} &middot; {durationLabel(preview.durationSeconds)}
          </p>
          <p className="muted">Duration will resolve from the live queue after sync.</p>
          <div className="row">
            <button onClick={() => void handleAdd()} disabled={instantSuccess?.syncing === true}>
              {instantSuccess?.syncing ? 'Syncing…' : 'Add to Queue'}
            </button>
            <button className="ghost" onClick={() => setPreview(null)}>
              Try Another URL
            </button>
          </div>
        </div>
      ) : null}

      {instantSuccess ? (
        <div className="card success">
          <h2>Added!</h2>
          {result ? (
            <p>
              &ldquo;{result.entry.title}&rdquo; is position{' '}
              <strong>{result.entry.position ?? '—'}</strong> in the queue.
            </p>
          ) : (
            <p>&ldquo;{instantSuccess.title}&rdquo; is showing in the queue while it syncs.</p>
          )}
          {instantSuccess.syncing ? <p className="badge badge-syncing">Syncing</p> : null}
          {instantSuccess.notice ? <p className="warn-text">{instantSuccess.notice}</p> : null}
          <div className="row">
            <Link className="button-link" to={`/join/${joinCode}/queue`}>
              View Queue
            </Link>
            <button
              className="ghost"
              onClick={() => {
                setResult(null)
                setPreview(null)
                setInstantSuccess(null)
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
