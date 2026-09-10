// Client-side YouTube helpers for optimistic song adds. oEmbed is keyless and
// quota-free, so it can provide title/channel/thumbnail immediately while the
// backend syncs the authoritative queue in the background.

const VIDEO_ID_RE = /^[A-Za-z0-9_-]{11}$/
const CACHE_KEY = 'karaoke:youtube-metadata:v1'

export interface ClientVideoMetadata {
  videoId: string
  youtubeUrl: string
  title: string
  channel: string
  thumbnailUrl: string
  durationSeconds: number | null
}

interface YouTubeOEmbedResponse {
  title?: unknown
  author_name?: unknown
  thumbnail_url?: unknown
}

type MetadataCache = Record<string, ClientVideoMetadata>

export function extractYouTubeVideoId(rawUrl: string): string | null {
  let parsed: URL
  try {
    parsed = new URL(rawUrl.trim())
  } catch {
    return null
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null
  const host = parsed.hostname.toLowerCase()

  if (host === 'youtu.be' || host === 'www.youtu.be') {
    const segments = parsed.pathname.split('/').filter(Boolean)
    if (segments.length !== 1) return null
    return VIDEO_ID_RE.test(segments[0]) ? segments[0] : null
  }

  if (
    host === 'youtube.com' ||
    host === 'www.youtube.com' ||
    host === 'm.youtube.com' ||
    host === 'music.youtube.com'
  ) {
    if (parsed.pathname === '/watch' || parsed.pathname.startsWith('/watch/')) {
      const videoId = parsed.searchParams.get('v')
      return videoId && VIDEO_ID_RE.test(videoId) ? videoId : null
    }
    const segments = parsed.pathname.split('/').filter(Boolean)
    if (segments.length === 2 && (segments[0] === 'embed' || segments[0] === 'shorts')) {
      return VIDEO_ID_RE.test(segments[1]) ? segments[1] : null
    }
  }
  return null
}

export function canonicalYouTubeUrl(videoId: string): string {
  return `https://www.youtube.com/watch?v=${videoId}`
}

function fallbackMetadata(videoId: string): ClientVideoMetadata {
  return {
    videoId,
    youtubeUrl: canonicalYouTubeUrl(videoId),
    title: 'Song syncing…',
    channel: 'YouTube',
    thumbnailUrl: `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`,
    durationSeconds: null,
  }
}

export function loadCachedVideoMetadata(videoId: string): ClientVideoMetadata | null {
  try {
    const raw = window.localStorage.getItem(CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as MetadataCache
    return parsed[videoId] ?? null
  } catch {
    return null
  }
}

export function saveCachedVideoMetadata(metadata: ClientVideoMetadata): void {
  try {
    const raw = window.localStorage.getItem(CACHE_KEY)
    const parsed = raw ? (JSON.parse(raw) as MetadataCache) : {}
    parsed[metadata.videoId] = metadata
    window.localStorage.setItem(CACHE_KEY, JSON.stringify(parsed))
  } catch {
    // Cache failures should never block song submission.
  }
}

export async function fetchOEmbedMetadata(youtubeUrl: string): Promise<ClientVideoMetadata> {
  const videoId = extractYouTubeVideoId(youtubeUrl)
  if (!videoId) throw new Error("that doesn't look like a valid YouTube link")

  const cached = loadCachedVideoMetadata(videoId)
  if (cached) return cached

  const canonicalUrl = canonicalYouTubeUrl(videoId)
  const endpoint = new URL('https://www.youtube.com/oembed')
  endpoint.searchParams.set('url', canonicalUrl)
  endpoint.searchParams.set('format', 'json')

  try {
    const response = await fetch(endpoint)
    if (!response.ok) return fallbackMetadata(videoId)
    const payload = (await response.json()) as YouTubeOEmbedResponse
    if (typeof payload.title !== 'string' || payload.title.trim() === '') {
      return fallbackMetadata(videoId)
    }

    const metadata: ClientVideoMetadata = {
      videoId,
      youtubeUrl: canonicalUrl,
      title: payload.title,
      channel: typeof payload.author_name === 'string' ? payload.author_name : '',
      thumbnailUrl: typeof payload.thumbnail_url === 'string' ? payload.thumbnail_url : '',
      durationSeconds: null,
    }
    saveCachedVideoMetadata(metadata)
    return metadata
  } catch {
    return fallbackMetadata(videoId)
  }
}

export function cacheQueueEntryMetadata(entry: {
  video_id: string
  youtube_url: string
  title: string
  channel: string
  thumbnail_url: string
  duration_seconds: number
}): void {
  saveCachedVideoMetadata({
    videoId: entry.video_id,
    youtubeUrl: entry.youtube_url,
    title: entry.title,
    channel: entry.channel,
    thumbnailUrl: entry.thumbnail_url,
    durationSeconds: entry.duration_seconds,
  })
}
