// Host dashboard (M9, PRODUCT_SPEC §5.3-5.7 / §7.4): the host's single control
// screen for the projector — current singer/song, playback status, the YouTube
// host player (M12, D4), full queue (names, titles, durations), QR + join code,
// and moderation actions driven by the M4/M7/M11 host endpoints.
//
// Queue/session state is always re-read from the backend; the screen subscribes
// to the M10 realtime channel and only falls back to polling while disconnected
// (D2, D5, B13). The embedded YouTube player plays the SINGING entry's video on
// the host device and reports completion back via the M11 finish endpoint.
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'

import { fetchQueueSnapshot, removeEntry, editEntryVideo } from '../../api/entries'
import { ApiError } from '../../api/client'
import {
  advancePlayback,
  endPlayback,
  endSession,
  fetchSession,
  fetchSessionQr,
  finishPlayback,
  pausePlayback,
  reorderSession,
  resetSessionOrder,
  resumePlayback,
  skipPlayback,
  startPlayback,
  startSession,
} from '../../api/host'
import type { PlaybackState, QueueEntry, QueueSnapshot, Session } from '../../api/types'
import { formatDuration } from '../../lib/format'
import { loadHostIdentity } from '../../lib/hostToken'
import { statusLabel } from '../../lib/session'
import { useTransitionRemaining } from '../../lib/transition'
import { useRealtime } from '../../ws/useRealtime'
import YouTubePlayer from './YouTubePlayer'

const POLL_INTERVAL_MS = 5000

function entryStatusLabel(status: QueueEntry['status']): string {
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

function playbackLabel(state: PlaybackState | undefined): string {
  switch (state) {
    case 'PLAYING':
      return 'Playing'
    case 'IDLE':
      return 'Idle'
    case 'PREPARING':
      return 'Preparing'
    case 'COUNTDOWN':
      return 'Countdown'
    case 'COOLDOWN':
      return 'Cooldown'
    case 'FINISHED':
      return 'Finished'
    case 'SKIPPED':
      return 'Skipped'
    default:
      return '—'
  }
}

export default function HostDashboardScreen() {
  const { sessionId = '' } = useParams()
  const [identity] = useState(loadHostIdentity)

  const [session, setSession] = useState<Session | null>(null)
  const [snapshot, setSnapshot] = useState<QueueSnapshot | null>(null)
  const [qrSvg, setQrSvg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [playerError, setPlayerError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editUrl, setEditUrl] = useState('')
  const [connected, setConnected] = useState(false)

  // Latest current singer, so the player's onEnded handler can guard against
  // finishing an entry that was already skipped/removed.
  const nowSingingRef = useRef<QueueEntry | null>(null)
  nowSingingRef.current = snapshot?.queue.find((e) => e.status === 'SINGING') ?? null

  const refreshQueue = useCallback(async () => {
    try {
      setSnapshot(await fetchQueueSnapshot(sessionId))
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the queue')
    }
  }, [sessionId])

  const refreshSession = useCallback(async () => {
    if (!identity) return
    try {
      setSession(await fetchSession(identity.token, sessionId))
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the session')
    }
  }, [identity, sessionId])

  const refreshAll = useCallback(async () => {
    // The session + queue endpoints are independent; a failure in one must
    // not prevent the other from updating (B13 fallback while disconnected).
    await Promise.allSettled([refreshSession(), refreshQueue()])
  }, [refreshSession, refreshQueue])

  // Initial authoritative fetch + the (immutable) QR code.
  useEffect(() => {
    if (!identity) return
    void refreshAll()
    fetchSessionQr(identity.token, sessionId)
      .then(setQrSvg)
      .catch(() => setQrSvg(null))
  }, [identity, sessionId, refreshAll])

  // Fallback while realtime is unavailable (B13): poll the authoritative
  // snapshot so the dashboard still updates if the WebSocket fails.
  useEffect(() => {
    if (connected || !identity) return
    const timer = setInterval(() => void refreshAll(), POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [connected, identity, refreshAll])

  useRealtime(sessionId, identity?.token ?? '', {
    onEvent: (event) => {
      if (event.type === 'QueueUpdated') {
        setSnapshot(event.snapshot)
      } else if (event.type === 'SessionUpdated') {
        // Keep the status badge / ended card in sync without a refetch.
        setSession((prev) => (prev ? { ...prev, status: event.status } : prev))
      }
    },
    onStatusChange: (isConnected) => {
      setConnected(isConnected)
      // D5: re-fetch authoritative state when the socket (re)connects.
      if (isConnected) void refreshAll()
    },
  })

  // M13 automatic transitions: count down to the authoritative deadline and
  // call advance when it passes (the backend owns the timing, D47). Placed
  // before the identity early-return so the hook always runs in the same order.
  const inTransition =
    snapshot?.playback_state === 'COOLDOWN' || snapshot?.playback_state === 'COUNTDOWN'
  const transitionRemaining = useTransitionRemaining(
    inTransition ? (snapshot?.transition_until ?? null) : null,
    () => void handlePlayback('advance'),
  )

  if (!identity) {
    return <Navigate to="/host/login" replace />
  }

  async function handleStart() {
    if (!identity || busy) return
    setBusy('start')
    setError(null)
    try {
      await startSession(identity.token, sessionId)
      await refreshSession()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start the session')
    } finally {
      setBusy(null)
    }
  }

  async function handleEnd() {
    if (!identity || busy) return
    if (!window.confirm('End this karaoke session for good?')) return
    setBusy('end')
    setError(null)
    try {
      await endSession(identity.token, sessionId)
      await refreshSession()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not end the session')
    } finally {
      setBusy(null)
    }
  }

  // M11/M13 playback controls: the endpoints return the authoritative snapshot,
  // so the dashboard renders it directly (the realtime channel also delivers it).
  async function handlePlayback(
    action: 'start' | 'end' | 'skip' | 'finish' | 'advance' | 'pause' | 'resume',
  ) {
    if (!identity || busy) return
    setBusy(action)
    setError(null)
    setPlayerError(null)
    try {
      const callbacks: Record<
        'start' | 'end' | 'skip' | 'finish' | 'advance' | 'pause' | 'resume',
        () => Promise<QueueSnapshot>
      > = {
        start: () => startPlayback(identity.token, sessionId),
        end: () => endPlayback(identity.token, sessionId),
        skip: () => skipPlayback(identity.token, sessionId),
        finish: () => finishPlayback(identity.token, sessionId),
        advance: () => advancePlayback(identity.token, sessionId),
        pause: () => pausePlayback(identity.token, sessionId),
        resume: () => resumePlayback(identity.token, sessionId),
      }
      const snapshot = await callbacks[action]()
      setSnapshot(snapshot)
      // Keep the session badge in sync (pause/resume change the session status).
      setSession((prev) => (prev ? { ...prev, status: snapshot.status } : prev))
    } catch (err) {
      // A stale advance (the deadline already passed elsewhere, e.g. another
      // tab) is a harmless 409 — the snapshot re-syncs via the realtime channel.
      if (!(action === 'advance' && err instanceof ApiError && err.status === 409)) {
        setError(err instanceof Error ? err.message : `Could not ${action} playback`)
      }
    } finally {
      setBusy(null)
    }
  }

  async function handleRemove(entry: QueueEntry) {
    if (!identity || busy) return
    setBusy(`remove:${entry.id}`)
    setError(null)
    try {
      await removeEntry(entry.id, identity.token)
      await refreshQueue()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not remove the entry')
    } finally {
      setBusy(null)
    }
  }

  // Per-round reorder (queue revision): move a participant up/down within the
  // current round. The backend returns the authoritative snapshot.
  async function handleReorder(index: number, direction: 'up' | 'down') {
    if (!identity || busy || !snapshot) return
    const swap = direction === 'up' ? index - 1 : index + 1
    if (swap < 0 || swap >= snapshot.queue.length) return
    const names = snapshot.queue.map((e) => e.participant_name)
    ;[names[index], names[swap]] = [names[swap], names[index]]
    setBusy(`order:${index}`)
    setError(null)
    try {
      const updated = await reorderSession(identity.token, sessionId, names)
      setSnapshot(updated)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not reorder the queue')
    } finally {
      setBusy(null)
    }
  }

  async function handleResetOrder() {
    if (!identity || busy) return
    setBusy('order:reset')
    setError(null)
    try {
      const updated = await resetSessionOrder(identity.token, sessionId)
      setSnapshot(updated)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not reset the queue order')
    } finally {
      setBusy(null)
    }
  }

  function beginEdit(entry: QueueEntry) {
    setEditingId(entry.id)
    setEditUrl(entry.youtube_url)
    setError(null)
  }

  async function handleEditSave(entry: QueueEntry) {
    if (!identity || busy) return
    if (editUrl.trim() === '') return
    setBusy(`edit:${entry.id}`)
    setError(null)
    setPlayerError(null)
    try {
      await editEntryVideo(entry.id, identity.token, editUrl.trim())
      setEditingId(null)
      await refreshQueue()
    } catch (err) {
      // E7: invalid replacement is rejected; the old URL is kept.
      setError(err instanceof Error ? err.message : 'Could not update the song')
    } finally {
      setBusy(null)
    }
  }

  if (!session) {
    return (
      <div className="host-dashboard">
        <div className="card host-loading-card">
          <p className="label">Host dashboard</p>
          <h1>Loading session…</h1>
          <p className="muted">
            {error ?? 'Preparing the projector view and live queue.'}
          </p>
        </div>
      </div>
    )
  }

  const ended = session.status === 'ENDED'
  const nowSinging = snapshot?.queue.find((e) => e.status === 'SINGING') ?? null
  const upNext =
    snapshot?.queue.find(
      (e) => e.id !== nowSinging?.id && e.status !== 'SINGING',
    ) ?? null

  // M16: per-participant remaining-song counts (the row shows "N more").
  const remainingByNickname = new Map(
    snapshot?.participants.map((p) => [p.nickname, p.remaining_songs]) ?? [],
  )

  return (
    <div className="host-dashboard">
      <header className="host-header">
        <div className="host-title">
          <h1>{session.name}</h1>
          <p className={`badge badge-${session.status.toLowerCase()}`}>
            {statusLabel(session.status)}
          </p>
        </div>
        <div className="host-join">
          {qrSvg ? (
            <img
              src={`data:image/svg+xml;utf8,${encodeURIComponent(qrSvg)}`}
              alt="Join QR code"
              className="qr"
            />
          ) : null}
          <div className="host-join-text">
            <span className="label">Join code</span>
            <strong className="join-code">{session.join_code}</strong>
            <span className="muted join-url">{session.join_url}</span>
          </div>
        </div>
      </header>

      {ended ? (
        <div className="card host-ended">
          <h2>This session has ended.</h2>
          <Link className="button-link" to="/host">
            Back to dashboard
          </Link>
        </div>
      ) : (
        <>
          <section className="host-main">
            <div className="host-now">
              <div className="card highlight">
                <p className="label">Now singing</p>
                {nowSinging ? (
                  <>
                    <h2>{nowSinging.title}</h2>
                    <p className="muted">
                      {nowSinging.participant_name} &middot;{' '}
                      {formatDuration(nowSinging.duration_seconds)}
                    </p>
                  </>
                ) : (
                  <p className="muted">Nobody yet — waiting for the queue.</p>
                )}
              </div>
              <div className="card">
                <p className="label">Up next</p>
                {upNext ? (
                  <>
                    <h3>{upNext.title}</h3>
                    <p className="muted">
                      {upNext.participant_name} &middot;{' '}
                      {formatDuration(upNext.duration_seconds)}
                    </p>
                  </>
                ) : (
                  <p className="muted">Queue is empty.</p>
                )}
              </div>
              <div className="card">
                <p className="label">Playback</p>
                <p>{snapshot ? playbackLabel(snapshot.playback_state) : '—'}</p>
                {/* The host browser is the playback device (D4, M12): the
                    player plays the current SINGING entry's video on the host
                    machine. A natural video end is reported via play/end (M13),
                    which starts the cooldown → countdown → auto-start. */}
                <YouTubePlayer
                  videoId={nowSingingRef.current?.video_id ?? null}
                  playerKey={nowSingingRef.current?.id ?? null}
                  onEnded={() => {
                    // Guard: only advance when this video is still the singer
                    // (the host may have skipped/removed it meanwhile).
                    if (nowSingingRef.current) void handlePlayback('end')
                  }}
                  onError={setPlayerError}
                />
                {playerError ? (
                  <p className="error-text">{playerError}</p>
                ) : null}
                {inTransition && transitionRemaining !== null ? (
                  <p className="muted transition-note">
                    {snapshot.playback_state === 'COOLDOWN'
                      ? 'Rest before the next singer'
                      : 'Next singer starts'}{' '}
                    in {Math.ceil(transitionRemaining)}s
                  </p>
                ) : null}
              </div>
            </div>

            <div className="host-actions">
              {session.status === 'CREATED' ? (
                <button onClick={() => void handleStart()} disabled={busy !== null}>
                  {busy === 'start' ? 'Starting…' : 'Start session'}
                </button>
              ) : null}
              {!nowSinging && snapshot && snapshot.queue.length > 0 ? (
                <button
                  onClick={() => void handlePlayback('start')}
                  disabled={busy !== null}
                >
                  {busy === 'start' ? 'Starting…' : 'Start next song'}
                </button>
              ) : null}
              <button
                className="ghost"
                onClick={() => void handlePlayback('skip')}
                disabled={busy !== null || !nowSinging}
                title={nowSinging ? undefined : 'No song is currently playing'}
              >
                {busy === 'skip' ? 'Skipping…' : 'Skip'}
              </button>
              <button
                className="ghost"
                onClick={() => void handlePlayback('finish')}
                disabled={busy !== null || !nowSinging}
                title={nowSinging ? undefined : 'No song is currently playing'}
              >
                {busy === 'finish' ? 'Finishing…' : 'Finish'}
              </button>
              {session.status === 'ACTIVE' ? (
                <button
                  className="ghost"
                  onClick={() => void handlePlayback('pause')}
                  disabled={busy !== null}
                >
                  {busy === 'pause' ? 'Pausing…' : 'Pause'}
                </button>
              ) : null}
              {session.status === 'PAUSED' ? (
                <button
                  className="ghost"
                  onClick={() => void handlePlayback('resume')}
                  disabled={busy !== null}
                >
                  {busy === 'resume' ? 'Resuming…' : 'Resume'}
                </button>
              ) : null}
              <button className="danger" onClick={() => void handleEnd()} disabled={busy !== null}>
                {busy === 'end' ? 'Ending…' : 'End session'}
              </button>
            </div>
          </section>

          <section className="host-queue">
            <div className="row queue-head">
              <h2>
                Queue
                {snapshot
                  ? ` · Round ${snapshot.round_number}${snapshot.rounds_completed > 0 ? ` (${snapshot.rounds_completed} completed)` : ''}`
                  : ''}
              </h2>
              <button
                className="ghost"
                onClick={() => void handleResetOrder()}
                disabled={busy !== null}
                title="Back to join order for this round"
              >
                Reset to join order
              </button>
            </div>
            {snapshot === null ? (
              <p className="muted">Loading queue…</p>
            ) : snapshot.queue.length === 0 ? (
              <p className="muted">No songs yet — waiting for singers.</p>
            ) : (
              <ol className="queue-list">
                {snapshot.queue.map((entry, index) => {
                  const editing = editingId === entry.id
                  const moreSongs =
                    (remainingByNickname.get(entry.participant_name) ?? 0) - 1
                  const isSinging = entry.status === 'SINGING'
                  // The current singer is fixed: you cannot move them, nor swap
                  // a neighbor through their position.
                  const aboveIsSinging =
                    index > 0 && snapshot.queue[index - 1].status === 'SINGING'
                  const belowIsSinging =
                    index < snapshot.queue.length - 1 &&
                    snapshot.queue[index + 1].status === 'SINGING'
                  return (
                    <li key={entry.id}>
                      <span className="position">{entry.position ?? '—'}</span>
                      <div className="entry-main">
                        <strong>{entry.title}</strong>
                        <span className="muted">
                          {entry.participant_name} &middot;{' '}
                          {formatDuration(entry.duration_seconds)} &middot;{' '}
                          {entryStatusLabel(entry.status)}
                          {moreSongs > 0 ? ` · ${moreSongs} more` : ''}
                        </span>
                        {editing ? (
                          <div className="stack host-edit">
                            <input
                              type="url"
                              value={editUrl}
                              onChange={(e) => setEditUrl(e.target.value)}
                              placeholder="New YouTube URL"
                              aria-label="New YouTube URL"
                              required
                            />
                            <div className="row">
                              <button
                                onClick={() => void handleEditSave(entry)}
                                disabled={busy !== null || editUrl.trim() === ''}
                              >
                                {busy === `edit:${entry.id}` ? 'Saving…' : 'Save'}
                              </button>
                              <button className="ghost" onClick={() => setEditingId(null)}>
                                Cancel
                              </button>
                            </div>
                          </div>
                        ) : null}
                      </div>
                      {!editing ? (
                        <div className="row entry-actions">
                          <button
                            className="ghost"
                            aria-label={`Move ${entry.participant_name} up`}
                            onClick={() => void handleReorder(index, 'up')}
                            disabled={
                              busy !== null || isSinging || index === 0 || aboveIsSinging
                            }
                            title={
                              isSinging
                                ? 'The current singer is fixed'
                                : 'Move up in this round'
                            }
                          >
                            ↑
                          </button>
                          <button
                            className="ghost"
                            aria-label={`Move ${entry.participant_name} down`}
                            onClick={() => void handleReorder(index, 'down')}
                            disabled={
                              busy !== null ||
                              isSinging ||
                              index === snapshot.queue.length - 1 ||
                              belowIsSinging
                            }
                            title={
                              isSinging
                                ? 'The current singer is fixed'
                                : 'Move down in this round'
                            }
                          >
                            ↓
                          </button>
                          <button
                            className="ghost"
                            onClick={() => beginEdit(entry)}
                            disabled={busy !== null}
                          >
                            Edit
                          </button>
                          <button
                            className="danger"
                            onClick={() => void handleRemove(entry)}
                            disabled={busy !== null}
                          >
                            {busy === `remove:${entry.id}` ? 'Removing…' : 'Remove'}
                          </button>
                        </div>
                      ) : null}
                    </li>
                  )
                })}
              </ol>
            )}
            {error ? <p className="error-text">{error}</p> : null}
          </section>
        </>
      )}
    </div>
  )
}
