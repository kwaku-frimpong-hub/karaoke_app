// useRealtime: subscribe a component to a session's realtime event stream.
//
// Delivery only (D5): events update what the screen renders, but the backend
// remains the source of truth. The hook auto-reconnects with a fixed delay;
// on reconnect the caller must re-fetch authoritative state (the screens do
// this by resuming their REST polling while disconnected).

import { useEffect, useRef } from 'react'

import { parseRealtimeEvent, realtimeWsUrl, type RealtimeEvent } from './client'

const RECONNECT_DELAY_MS = 3000

export interface RealtimeHandlers {
  /** Called for every typed event delivered by the backend. */
  onEvent: (event: RealtimeEvent) => void
  /** Called when the connection opens (true) or drops (false). */
  onStatusChange?: (connected: boolean) => void
}

/** Subscribe to ``sessionId``'s realtime events using ``token`` as the bearer
 *  credential. Returns nothing; callbacks are kept up to date via a ref so the
 *  connection survives re-renders. */
export function useRealtime(
  sessionId: string,
  token: string,
  handlers: RealtimeHandlers,
): void {
  const handlersRef = useRef(handlers)
  handlersRef.current = handlers

  useEffect(() => {
    if (!sessionId || !token) return

    let socket: WebSocket | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let disposed = false

    const connect = (): void => {
      socket = new WebSocket(realtimeWsUrl(sessionId, token))
      socket.onopen = () => {
        if (disposed) return
        handlersRef.current.onStatusChange?.(true)
      }
      socket.onmessage = (message) => {
        if (disposed) return
        const event = parseRealtimeEvent(message.data as string)
        if (event !== null) handlersRef.current.onEvent(event)
      }
      socket.onclose = () => {
        if (disposed) return
        handlersRef.current.onStatusChange?.(false)
        reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS)
      }
      socket.onerror = () => {
        // onclose always follows; nothing to do here.
      }
    }

    connect()

    return () => {
      disposed = true
      if (reconnectTimer !== null) clearTimeout(reconnectTimer)
      socket?.close()
    }
  }, [sessionId, token])
}
