// YouTube host player (M12): embeds the YouTube IFrame player on the host
// dashboard — the host browser is the playback device (D4), so participants'
// phones never play audio.
//
// The component loads the current SINGING entry's video whenever `videoId`
// changes and reports playback completion/errors back to the caller, which
// translates them into backend actions (finish/skip, M11). Playback is
// attempted on load; browser autoplay policies may leave the video paused, in
// which case the host uses the embedded player's native controls (E24).
import { useEffect, useRef, useState } from 'react'

interface YouTubePlayerProps {
  /** The video to play (the SINGING entry's id), or null to stop. */
  videoId: string | null
  /** A stable per-entry key: consecutive entries with the same video id
   *  (duplicate songs, B16) must still replay, so reload on entry change. */
  playerKey: string | null
  /** Called when the current video reaches its end (→ backend finish). */
  onEnded: () => void
  /** Called with a human-readable message when the player errors (E5/E24). */
  onError: (message: string) => void
}

let apiPromise: Promise<void> | null = null

/** Load the YouTube IFrame API script exactly once; resolves when ready. */
function loadYouTubeApi(): Promise<void> {
  if (apiPromise) return apiPromise
  apiPromise = new Promise<void>((resolve) => {
    if (window.YT?.Player) {
      resolve()
      return
    }
    const previous = window.onYouTubeIframeAPIReady
    window.onYouTubeIframeAPIReady = () => {
      previous?.()
      resolve()
    }
    const script = document.createElement('script')
    script.src = 'https://www.youtube.com/iframe_api'
    script.async = true
    document.head.appendChild(script)
  })
  return apiPromise
}

/** Map the YouTube player error codes to a host-facing message (E5/E24). */
function playerErrorMessage(code: number): string {
  switch (code) {
    case 2:
      return 'This video is not available.'
    case 5:
      return 'The player could not play this video.'
    case 100:
      return 'This video is no longer available.'
    case 101:
    case 150:
      return 'Embedding this video is not allowed.'
    default:
      return 'The video could not be played.'
  }
}

export default function YouTubePlayer({ videoId, playerKey, onEnded, onError }: YouTubePlayerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const playerRef = useRef<YT.Player | null>(null)
  const lastKeyRef = useRef<string | null>(null)
  const lastLoadedRef = useRef<string | null>(null)
  const [ready, setReady] = useState(false)

  // Keep the latest callbacks in refs so the player events always see the
  // current render's handlers without recreating the player.
  const onEndedRef = useRef(onEnded)
  onEndedRef.current = onEnded
  const onErrorRef = useRef(onError)
  onErrorRef.current = onError

  // Create the player once, bound to the (always-mounted) container.
  useEffect(() => {
    let cancelled = false
    void loadYouTubeApi().then(() => {
      if (cancelled || !containerRef.current) return
      playerRef.current = new window.YT!.Player(containerRef.current, {
        height: '100%',
        width: '100%',
        playerVars: { playsinline: 1, rel: 0 },
        events: {
          onReady: () => setReady(true),
          onStateChange: (event) => {
            if (event.data === window.YT!.PlayerState.ENDED) {
              onEndedRef.current()
            }
          },
          onError: (event) => onErrorRef.current(playerErrorMessage(event.data)),
        },
      })
    })
    return () => {
      cancelled = true
      playerRef.current?.destroy()
      playerRef.current = null
    }
  }, [])

  // Drive the player from the current entry/video.
  useEffect(() => {
    const player = playerRef.current
    if (!player || !ready) return
    if (!videoId || !playerKey) {
      player.stopVideo()
      lastKeyRef.current = null
      lastLoadedRef.current = null
      return
    }
    // Reload when the entry changes (even if the video id is the same — two
    // participants can queue the same song, B16) or when the entry's video was
    // edited. Track what we loaded ourselves — getVideoData() is stale after
    // stopVideo(). Playback is attempted on load; if a browser blocks it the
    // native controls remain usable (E24).
    if (lastKeyRef.current !== playerKey || lastLoadedRef.current !== videoId) {
      lastKeyRef.current = playerKey
      lastLoadedRef.current = videoId
      player.loadVideoById(videoId)
      player.playVideo()
    }
  }, [videoId, playerKey, ready])

  return (
    <div className="player">
      <div className="player-frame" ref={containerRef} />
      {!videoId ? (
        <div className="player-placeholder">No song is playing.</div>
      ) : null}
      {!ready ? <p className="muted player-status">Loading player…</p> : null}
    </div>
  )
}
