import { useEffect, useState } from 'react'
import { api, type DemoInfo } from './api'

export function useDemo() {
  const [demo, setDemo] = useState<DemoInfo | null>(null)
  useEffect(() => {
    let stop = false
    const load = () => api<DemoInfo>('/v1/demo').then((d) => !stop && setDemo(d)).catch(() => !stop && setTimeout(load, 2000))
    load()
    return () => { stop = true }
  }, [])
  return demo
}
