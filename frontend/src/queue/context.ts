import { createContext, useContext } from 'react'

import type { QueueEntry, QueueSnapshot, SessionStatus, SongSubmitResult } from '../api/types'
import type { ClientVideoMetadata } from '../lib/youtube'

export type OptimisticStatus = 'syncing' | 'failed'

export interface QueueDisplayEntry extends QueueEntry {
  optimistic_status?: OptimisticStatus
  optimistic_error?: string
  server_id?: string
}

export interface CacheableEntry {
  id: string
  video_id: string
  youtube_url: string
  title: string
  channel: string
  thumbnail_url: string
  duration_seconds: number
}

export interface BaseAddInput {
  sessionId: string
  token: string
  participantName: string
  metadata: ClientVideoMetadata
}

export interface HostAddInput extends BaseAddInput {
  participantId: string
}

export interface QueueContextValue {
  authoritativeSnapshot: QueueSnapshot | null
  displaySnapshot: QueueSnapshot | null
  pendingAction: string | null
  optimisticRemovalIds: Set<string>
  optimisticEntries: QueueDisplayEntry[]
  setAuthoritativeSnapshot: (snapshot: QueueSnapshot) => void
  updateSnapshotStatus: (status: SessionStatus) => void
  beginOptimisticSnapshot: (snapshot: QueueSnapshot, action: string) => void
  clearOptimisticSnapshot: () => void
  markOptimisticRemoval: (entryId: string) => void
  clearOptimisticRemoval: (entryId: string) => void
  clearOptimisticRemovals: () => void
  mergedQueue: (queue: QueueEntry[]) => QueueDisplayEntry[]
  mergedMine: (entries: QueueEntry[], participantName: string) => QueueDisplayEntry[]
  addParticipantSong: (input: BaseAddInput) => Promise<SongSubmitResult>
  addHostSong: (input: HostAddInput) => Promise<SongSubmitResult>
  clearSynced: (entries: CacheableEntry[]) => void
}

export const QueueContext = createContext<QueueContextValue | null>(null)

export function useQueueStore(): QueueContextValue {
  const value = useContext(QueueContext)
  if (value === null) throw new Error('useQueueStore must be used inside QueueProvider')
  return value
}
