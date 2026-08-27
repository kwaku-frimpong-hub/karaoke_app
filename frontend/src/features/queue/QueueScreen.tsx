// Participant queue screen (PRODUCT_SPEC §6.6/§7.3): subscribes to the session's
// realtime channel (M10) and renders the session status, now/next cards, and the
// queue with the participant's own entries highlighted. The backend is the source
// of truth — this screen only renders what it returns. While the WebSocket is
// disconnected it falls back to polling the authoritative snapshot (D5/B13).
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'

import { cancelEntry, fetchMyEntries, fetchQueueSnapshot, leaveSession } from '../../api/entries'
import type { QueueEntry, QueueSnapshot } from '../../api/types'
import { formatDuration } from '../../lib/format'
import { statusLabel } from '../../lib/session'
import { clearIdentity, loadIdentity } from '../../lib/token'
import { useTransitionRemaining } from '../../lib/transition'
import { useRealtime } from '../../ws/useRealtime'

const POLL_INTERVAL_MS = 5000
//: How long an in-app "you're next" banner stays visible (M15).
const NOTIFICATION_MS = 8000

export default function QueueScreen() {
  const { joinCode = '' } = useParams()
  const navigate = useNavigate()
  // Read the stored identity once so its reference (and thus the polling
  // effect below) stays stable across renders (avoids a fetch loop).
  const [identity] = useState(loadIdentity)

  const [snapshot, setSnapshot] = useState<QueueSnapshot | null>(null)
  const [mySongs, setMySongs] = useState<QueueEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [connected, setConnected] = useState(false)
  const [notification, setNotification] = useState<string | null>(null)
  const notifyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const showNotification = useCallback((message: string) => {
    setNotification(message)
    if (notifyTimerRef.current !== null) clearTimeout(notifyTimerRef.current)
    notifyTimerRef.current = setTimeout(() => setNotification(null), NOTIFICATION_MS)
  }, [])

  useEffect(
    () => () => {
      if (notifyTimerRef.current !== null) clearTimeout(notifyTimerRef.current)
    },
    [],
  )

  const refresh = useCallback(async () => {
    if (!identity) return
    try {
      const [snap, mine] = await Promise.all([
        fetchQueueSnapshot(identity.sessionId),
        fetchMyEntries(identity.sessionId, identity.token),
      ])
      setSnapshot(snap)
      setMySongs(mine)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the queue')
    }
  }, [identity])

  // Refresh only the participant's own songs (e.g. after a round advance the
  // host may have processed an entry, removing it from the non-terminal list).
  const refreshMySongs = useCallback(async () => {
    if (!identity) return
    try {
      setMySongs(await fetchMyEntries(identity.sessionId, identity.token))
    } catch {
      // Snapshot errors are surfaced by refresh(); keep the last-known list.
    }
  }, [identity])

  // Initial authoritative fetch; the live channel and the fallback poll below
  // keep the screen fresh afterwards.
  useEffect(() => {
    void refresh()
  }, [refresh])

  // Fallback while realtime is unavailable (B13): poll the authoritative
  // snapshot so the screen still updates if the WebSocket fails.
  useEffect(() => {
    if (connected) return
    const timer = setInterval(() => void refresh(), POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [connected, refresh])

  useRealtime(identity?.sessionId ?? '', identity?.token ?? '', {
    onEvent: (event) => {
      if (event.type === 'QueueUpdated') {
        setSnapshot(event.snapshot)
        void refreshMySongs()
      } else if (event.type === 'SessionUpdated') {
        // The snapshot carries the session status too; keep it in sync so the
        // ended banner appears without a queue mutation (M10).
        setSnapshot((prev) =>
          prev ? { ...prev, status: event.status } : prev,
        )
      } else if (event.type === 'NextSingerNotified') {
        // M15 in-app notification: only for the participant it concerns.
        if (identity && event.participant_name === identity.nickname) {
          showNotification(
            event.phase === 'next'
              ? `🎤 You're next! Get ready: ${event.title} — ${event.channel}`
              : `🎤 Starting soon! ${event.title} — ${event.channel}`,
          )
        }
      }
    },
    onStatusChange: (isConnected) => {
      setConnected(isConnected)
      // D5: re-fetch authoritative state when the socket (re)connects.
      if (isConnected) void refresh()
    },
  })

  // M13: show the next singer's countdown while an automatic transition runs.
  const inTransition =
    snapshot?.playback_state === 'COOLDOWN' || snapshot?.playback_state === 'COUNTDOWN'
  const transitionRemaining = useTransitionRemaining(
    inTransition ? (snapshot?.transition_until ?? null) : null,
  )

  async function handleCancel(entry: QueueEntry) {
    if (!identity) return
    try {
      await cancelEntry(entry.id, identity.token)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not cancel the entry')
    }
  }

  async function handleLeave() {
    if (!identity) return
    if (!window.confirm('Leave this karaoke session? Your songs will be removed.')) {
      return
    }
    try {
      await leaveSession(identity.sessionId, identity.token)
      clearIdentity()
      navigate(`/join/${joinCode}`, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not leave the session')
    }
  }

  if (!identity || identity.joinCode.toLowerCase() !== joinCode.toLowerCase()) {
    return <Navigate to={`/join/${joinCode}`} replace />
  }

  if (!snapshot) {
    return (
      <div className="screen">
        {identity ? (
          <header className="topbar">
            <span className="session-name">{identity.sessionName}</span>
            <Link to={`/join/${joinCode}/submit`}>+ Add Song</Link>
          </header>
        ) : null}
        <div className="card queue-loading-card">
          <p className="muted">{error ?? 'Loading the live queue…'}</p>
        </div>
      </div>
    )
  }

  const ended = snapshot.status === 'ENDED'
  const nowSinging = snapshot.queue.find((e) => e.status === 'SINGING')
  // "Up next" is the first queued entry that is not the current singer: the
  // backend's NEXT entry when one exists, otherwise the first WAITING entry.
  const upNext = snapshot.queue.find(
    (e) => e.id !== nowSinging?.id && e.status !== 'SINGING',
  )

  return (
    <div className="screen">
      <header className="topbar">
        <span className="session-name">{identity.sessionName}</span>
        <Link to={`/join/${joinCode}/submit`}>+ Add Song</Link>
      </header>

      {notification ? (
        <div className="card notify" role="status">
          <strong>{notification}</strong>
        </div>
      ) : null}

      <div className="row">
        <p className={`badge badge-${snapshot.status.toLowerCase()}`}>
          {statusLabel(snapshot.status)}
        </p>
        {!ended ? (
          <p className="badge badge-round">Round {snapshot.round_number}</p>
        ) : null}
      </div>

      {ended ? (
        <div className="card">
          <h2>This karaoke night has ended.</h2>
        </div>
      ) : (
        <>
          {nowSinging ? (
            <div className="card highlight">
              <p className="label">Now singing</p>
              <h2>{nowSinging.title}</h2>
              <p className="muted">{nowSinging.participant_name}</p>
            </div>
          ) : null}

          {upNext ? (
            <div className="card">
              <p className="label">Up next</p>
              <h3>{upNext.title}</h3>
              <p className="muted">
                {upNext.participant_name}
                {inTransition && transitionRemaining !== null
                  ? ` · starts in ${Math.ceil(transitionRemaining)}s`
                  : ''}
              </p>
            </div>
          ) : null}

          <section className="queue">
            <h2>Queue</h2>
            {snapshot.queue.length === 0 ? (
              <p className="muted">No songs yet — add the first one!</p>
            ) : (
              <ol className="queue-list">
                {snapshot.queue.map((entry) => {
                  const mine = entry.participant_name === identity.nickname
                  return (
                    <li key={entry.id} className={mine ? 'mine' : ''}>
                      <span className="position">
                        {entry.position ?? '—'}
                      </span>
                      <div className="entry-main">
                        <strong>{entry.title}</strong>
                        <span className="muted">
                          {entry.participant_name} &middot;{' '}
                          {formatDuration(entry.duration_seconds)}
                        </span>
                        {mine && entry.status === 'WAITING' ? (
                          <button
                            className="link-button"
                            onClick={() => void handleCancel(entry)}
                          >
                            Cancel
                          </button>
                        ) : null}
                      </div>
                    </li>
                  )
                })}
              </ol>
            )}
          </section>

          {mySongs && mySongs.length > 0 ? (
            <section className="queue">
              <h2>Your songs</h2>
              <ol className="queue-list">
                {mySongs.map((entry) => (
                  <li key={entry.id} className="mine">
                    <span className="position">{entry.position ?? '—'}</span>
                    <div className="entry-main">
                      <strong>{entry.title}</strong>
                      <span className="muted">
                        {entry.position !== null ? 'This round' : 'Upcoming'}{' '}
                        &middot; {formatDuration(entry.duration_seconds)}
                      </span>
                      {entry.status === 'WAITING' ? (
                        <button
                          className="link-button"
                          onClick={() => void handleCancel(entry)}
                        >
                          Cancel
                        </button>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ol>
            </section>
          ) : null}

          {error ? <p className="error-text">{error}</p> : null}

          <p className="leave-session">
            <button className="link-button" onClick={() => void handleLeave()}>
              Leave session
            </button>
          </p>
        </>
      )}
    </div>
  )
}
