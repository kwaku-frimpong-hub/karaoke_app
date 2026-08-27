// Minimal ambient types for the YouTube IFrame Player API (M12).
//
// The full API surface is much larger; we only declare what the host dashboard
// uses. The API script is loaded at runtime from
// https://www.youtube.com/iframe_api. Because this is a .d.ts, the YT
// namespace merges into the global scope and Window gains the YT members.

interface YTPlayerEvent {
  target: YT.Player
}

declare namespace YT {
  interface PlayerOptions {
    videoId?: string
    height?: string | number
    width?: string | number
    playerVars?: Record<string, string | number | boolean>
    events?: {
      onReady?: (event: YTPlayerEvent) => void
      onStateChange?: (event: YTPlayerEvent & { data: number }) => void
      onError?: (event: { data: number }) => void
    }
  }

  class Player {
    constructor(elementId: string | HTMLElement, options: PlayerOptions)
    loadVideoById(videoId: string, startSeconds?: number): void
    cueVideoById(videoId: string, startSeconds?: number): void
    playVideo(): void
    pauseVideo(): void
    stopVideo(): void
    destroy(): void
    getPlayerState(): number
    getVideoData(): { video_id?: string; title?: string; author?: string }
  }

  const PlayerState: {
    UNSTARTED: -1
    ENDED: 0
    PLAYING: 1
    PAUSED: 2
    BUFFERING: 3
    CUED: 5
  }
}

interface Window {
  YT?: typeof YT
  onYouTubeIframeAPIReady?: () => void
}
