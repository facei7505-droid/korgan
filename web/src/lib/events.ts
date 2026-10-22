import { useEffect, useRef, useState } from 'react'
import { API_KEY, API_URL, type QEvent } from './api'

/** Subscribe to the live event stream (Server-Sent Events), optionally only one customer's events. */
export function useEvents(onEvent: (e: QEvent) => void, customerId?: string) {
  const handler = useRef(onEvent)
  handler.current = onEvent
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    const q = new URLSearchParams({ key: API_KEY, ...(customerId ? { customer_id: customerId } : {}) })
    const es = new EventSource(`${API_URL}/v1/events/stream?${q}`)
    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false)
    es.onmessage = (m) => {
      try {
        handler.current(JSON.parse(m.data))
      } catch {
        /* ignore malformed */
      }
    }
    return () => es.close()
  }, [customerId])
  return connected
}

/** Short alert sound via WebAudio (no asset files). */
export function chime() {
  try {
    const ctx = new AudioContext()
    ;[880, 1320].forEach((f, i) => {
      const o = ctx.createOscillator()
      const g = ctx.createGain()
      o.frequency.value = f
      g.gain.setValueAtTime(0.0001, ctx.currentTime + i * 0.18)
      g.gain.exponentialRampToValueAtTime(0.3, ctx.currentTime + i * 0.18 + 0.02)
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + i * 0.18 + 0.3)
      o.connect(g).connect(ctx.destination)
      o.start(ctx.currentTime + i * 0.18)
      o.stop(ctx.currentTime + i * 0.18 + 0.32)
    })
    navigator.vibrate?.([200, 100, 200])
  } catch {
    /* audio not allowed until user gesture */
  }
}
