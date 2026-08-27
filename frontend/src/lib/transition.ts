// useTransitionRemaining: count down to an automatic-transition deadline (M13).
//
// The backend owns the transition timing (D47): the snapshot carries the
// authoritative absolute deadline (`transition_until`). This hook renders the
// remaining seconds and fires `onExpired` exactly once when the deadline
// passes, so the host dashboard can call `play/advance` to progress the
// cooldown/countdown. Reopened tabs with an overdue deadline self-recover:
// they render 0s and immediately fire `onExpired`.

import { useEffect, useRef, useState } from 'react'

export function useTransitionRemaining(
  transitionUntil: string | null,
  onExpired?: () => void,
): number | null {
  const [remaining, setRemaining] = useState<number | null>(null)
  const onExpiredRef = useRef(onExpired)
  onExpiredRef.current = onExpired

  useEffect(() => {
    if (!transitionUntil) {
      setRemaining(null)
      return
    }
    const deadline = Date.parse(transitionUntil)
    if (Number.isNaN(deadline)) {
      setRemaining(null)
      return
    }
    let fired = false
    const update = () => {
      const seconds = Math.max(0, (deadline - Date.now()) / 1000)
      setRemaining(seconds)
      if (seconds <= 0 && !fired) {
        fired = true
        onExpiredRef.current?.()
      }
    }
    update()
    const timer = setInterval(update, 250)
    return () => clearInterval(timer)
  }, [transitionUntil])

  return remaining
}
