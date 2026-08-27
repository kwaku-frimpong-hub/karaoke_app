// Shared session helpers used by both the participant queue screen and the
// host dashboard.

import type { SessionStatus } from '../api/types'

export function statusLabel(status: SessionStatus): string {
  switch (status) {
    case 'CREATED':
      return 'Waiting to start'
    case 'ACTIVE':
      return 'Live'
    case 'PAUSED':
      return 'Paused'
    case 'ENDED':
      return 'Ended'
  }
}
