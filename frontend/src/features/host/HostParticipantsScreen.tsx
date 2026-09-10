// Host participant management: a separate PC-first screen where the host can
// see singers and their queued playlists, create no-phone participants, and add
// songs to them without changing the main playback dashboard flow.
import { type FormEvent, useCallback, useEffect, useState } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'

import {
  createHostParticipant,
  fetchHostParticipants,
  fetchSession,
} from '../../api/host'
import type { HostParticipantDetail, HostParticipantEntry, Session } from '../../api/types'
import { formatDuration } from '../../lib/format'
import { loadHostIdentity } from '../../lib/hostToken'
import { statusLabel } from '../../lib/session'
import { fetchOEmbedMetadata } from '../../lib/youtube'
import { type QueueDisplayEntry, useQueueStore } from '../../queue/context'
import { useRealtime } from '../../ws/useRealtime'

const POLL_INTERVAL_MS = 5000

type PlaylistEntry = HostParticipantEntry | QueueDisplayEntry

function entryStatusLabel(status: HostParticipantEntry['status']): string {
  switch (status) {
    case 'WAITING':
      return 'Waiting'
    case 'NEXT':
      return 'Next up'
    case 'SINGING':
      return 'Now singing'
    case 'COMPLETED':
      return 'Done'
    case 'SKIPPED':
      return 'Skipped'
    case 'CANCELLED':
      return 'Cancelled'
    case 'REMOVED':
      return 'Removed'
  }
}

function isOptimisticEntry(entry: PlaylistEntry): entry is QueueDisplayEntry {
  return 'participant_name' in entry
}

function playlistDuration(entry: PlaylistEntry): string {
  if (isOptimisticEntry(entry) && entry.duration_seconds === 0) return 'duration resolving'
  if (entry.duration_seconds === 0) return 'duration unknown'
  return formatDuration(entry.duration_seconds)
}

export default function HostParticipantsScreen() {
  const { sessionId = '' } = useParams()
  const [identity] = useState(loadHostIdentity)
  const queueStore = useQueueStore()
  const { clearSynced } = queueStore

  const [session, setSession] = useState<Session | null>(null)
  const [participants, setParticipants] = useState<HostParticipantDetail[] | null>(null)
  const [nickname, setNickname] = useState('')
  const [songUrls, setSongUrls] = useState<Record<string, string>>({})
  const [selectedParticipantId, setSelectedParticipantId] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [connected, setConnected] = useState(false)

  const refresh = useCallback(async () => {
    if (!identity) return
    try {
      const [loadedSession, loadedParticipants] = await Promise.all([
        fetchSession(identity.token, sessionId),
        fetchHostParticipants(identity.token, sessionId),
      ])
      setSession(loadedSession)
      setParticipants(loadedParticipants)
      clearSynced(loadedParticipants.flatMap((participant) => participant.entries))
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load participants')
    }
  }, [clearSynced, identity, sessionId])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    if (connected || !identity) return
    const timer = setInterval(() => void refresh(), POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [connected, identity, refresh])

  useRealtime(sessionId, identity?.token ?? '', {
    onEvent: (event) => {
      if (
        event.type === 'QueueUpdated' ||
        event.type === 'ParticipantJoined' ||
        event.type === 'SessionUpdated'
      ) {
        void refresh()
      }
    },
    onStatusChange: (isConnected) => {
      setConnected(isConnected)
      if (isConnected) void refresh()
    },
  })

  if (!identity) {
    return <Navigate to="/host/login" replace />
  }

  const ended = session?.status === 'ENDED'

  async function handleCreateParticipant(event: FormEvent) {
    event.preventDefault()
    if (!identity || busy || nickname.trim() === '') return
    setBusy('create')
    setError(null)
    setNotice(null)
    try {
      const participant = await createHostParticipant(identity.token, sessionId, nickname.trim())
      setNickname('')
      setSelectedParticipantId(participant.id)
      setNotice(`${participant.nickname} was added to the session.`)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add this singer')
    } finally {
      setBusy(null)
    }
  }

  async function handleAddSong(event: FormEvent, participant: HostParticipantDetail) {
    event.preventDefault()
    if (!identity || busy) return
    const youtubeUrl = (songUrls[participant.id] ?? '').trim()
    if (youtubeUrl === '') return
    setBusy(`song:${participant.id}`)
    setError(null)
    setNotice(null)
    try {
      const metadata = await fetchOEmbedMetadata(youtubeUrl)
      const result = await queueStore.addHostSong({
        token: identity.token,
        sessionId,
        participantId: participant.id,
        participantName: participant.nickname,
        metadata,
      })
      setSongUrls((prev) => ({ ...prev, [participant.id]: '' }))
      setNotice(`Added “${result.entry.title}” for ${participant.nickname}.`)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add this song')
    } finally {
      setBusy(null)
    }
  }

  if (!session || !participants) {
    return (
      <div className="host-dashboard">
        <div className="card host-loading-card">
          <p className="label">Participants</p>
          <h1>Loading singers…</h1>
          <p className="muted">
            {error ?? 'Preparing the host participant view.'}
          </p>
        </div>
      </div>
    )
  }

  const selectedParticipant =
    participants.find((participant) => participant.id === selectedParticipantId) ?? null

  function participantPlaylist(participant: HostParticipantDetail): PlaylistEntry[] {
    return [
      ...participant.entries,
      ...queueStore.optimisticEntries.filter(
        (entry) => entry.participant_name === participant.nickname,
      ),
    ]
  }

  return (
    <div className="host-dashboard host-participants">
      <header className="host-header">
        <div className="host-title">
          <p className="label">Participant management</p>
          <h1>{session.name}</h1>
          <div className="row">
            <p className={`badge badge-${session.status.toLowerCase()}`}>
              {statusLabel(session.status)}
            </p>
            <Link className="button-link" to={`/host/sessions/${sessionId}`}>
              Back to dashboard
            </Link>
          </div>
        </div>
      </header>

      <section className="card stack">
        <div>
          <p className="label">Add a singer</p>
          <h2>No phone? Add them here.</h2>
          <p className="muted">
            Host-created singers stay host-managed and are not auto-cleaned for absence.
          </p>
        </div>
        <form className="row participant-create" onSubmit={(event) => void handleCreateParticipant(event)}>
          <div className="field participant-name-field">
            <label htmlFor="host-participant-nickname">Nickname</label>
            <input
              id="host-participant-nickname"
              type="text"
              value={nickname}
              onChange={(event) => setNickname(event.target.value)}
              placeholder="Singer nickname"
              disabled={ended || busy !== null}
              maxLength={20}
              required
            />
          </div>
          <button type="submit" disabled={ended || busy !== null || nickname.trim() === ''}>
            {busy === 'create' ? 'Adding…' : 'Add singer'}
          </button>
        </form>
      </section>

      {notice ? (
        <div className="card success" role="status">
          {notice}
        </div>
      ) : null}
      {error ? <p className="error-text">{error}</p> : null}

      <section className="host-participant-list">
        <div className="participant-list-head">
          <div>
            <p className="label">Choose a singer</p>
            <h2>Singers</h2>
          </div>
          <p className="muted">Click a card to open their playlist and add music.</p>
        </div>
        {participants.length === 0 ? (
          <div className="card">
            <p className="muted">No singers yet — add the first one above.</p>
          </div>
        ) : (
          <div className="participant-tile-grid">
            {participants.map((participant) => {
              const entries = participantPlaylist(participant)
              const latest = entries.at(-1)
              const selected = participant.id === selectedParticipant?.id
              return (
                <button
                  type="button"
                  className={`participant-tile${selected ? ' selected' : ''}`}
                  key={participant.id}
                  onClick={() => setSelectedParticipantId(participant.id)}
                  aria-pressed={selected}
                >
                  <span className="participant-avatar" aria-hidden="true">
                    {participant.nickname.trim().charAt(0).toUpperCase() || '♪'}
                  </span>
                  <span className="participant-tile-copy">
                    <strong>{participant.nickname}</strong>
                    <span className="muted">
                      {entries.length} queued{latest ? ` · ${latest.title}` : ''}
                    </span>
                  </span>
                  <span className="badge badge-round">Open</span>
                </button>
              )
            })}
          </div>
        )}
      </section>

      {participants.length > 0 && !selectedParticipant ? (
        <section className="card participant-empty-detail">
          <p className="label">Playlist</p>
          <h2>Select a singer</h2>
          <p className="muted">Choose a card above to add music to that singer&apos;s list.</p>
        </section>
      ) : null}

      {selectedParticipant ? (
        <section className="card stack participant-detail-panel">
          <div className="row participant-card-head">
            <div>
              <p className="label">Selected singer</p>
              <h2>{selectedParticipant.nickname}</h2>
              <p className="muted">Add songs only for this singer here.</p>
            </div>
            <p className="badge badge-round">
              {participantPlaylist(selectedParticipant).length} queued
            </p>
          </div>

          <form
            className="row participant-song-form"
            onSubmit={(event) => void handleAddSong(event, selectedParticipant)}
          >
            <div className="field participant-song-field">
              <label htmlFor={`song-url-${selectedParticipant.id}`}>YouTube link</label>
              <input
                id={`song-url-${selectedParticipant.id}`}
                type="url"
                value={songUrls[selectedParticipant.id] ?? ''}
                onChange={(event) =>
                  setSongUrls((prev) => ({
                    ...prev,
                    [selectedParticipant.id]: event.target.value,
                  }))
                }
                placeholder="Paste a YouTube link"
                disabled={ended || busy !== null}
                required
              />
            </div>
            <button
              type="submit"
              disabled={
                ended ||
                busy !== null ||
                (songUrls[selectedParticipant.id] ?? '').trim() === ''
              }
            >
              {busy === `song:${selectedParticipant.id}` ? 'Adding…' : 'Add song'}
            </button>
          </form>

          {participantPlaylist(selectedParticipant).length === 0 ? (
            <p className="muted">No queued songs yet for this singer.</p>
          ) : (
            <ol className="queue-list participant-playlist">
              {participantPlaylist(selectedParticipant).map((entry) => (
                <li key={entry.id} className={isOptimisticEntry(entry) ? 'optimistic' : ''}>
                  <span className="position">{entry.position ?? '—'}</span>
                  <div className="entry-main">
                    <strong>{entry.title}</strong>
                    <span className="muted">
                      {isOptimisticEntry(entry)
                        ? 'Syncing'
                        : `Round ${entry.round_number} · ${entryStatusLabel(entry.status)}`}{' '}
                      &middot; {playlistDuration(entry)}
                    </span>
                    {isOptimisticEntry(entry) && entry.optimistic_status ? (
                      <span className={`badge badge-${entry.optimistic_status}`}>
                        {entry.optimistic_status === 'syncing' ? 'Syncing' : 'Failed'}
                      </span>
                    ) : null}
                    {isOptimisticEntry(entry) && entry.optimistic_error ? (
                      <span className="error-text">{entry.optimistic_error}</span>
                    ) : null}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </section>
      ) : null}
    </div>
  )
}
