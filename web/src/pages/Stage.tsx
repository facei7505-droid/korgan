import { useState } from 'react'
import { BankApp } from '../components/BankApp'
import { ControlPanel } from '../components/ControlPanel'
import { EventFeed } from '../components/EventFeed'
import { GuardianApp } from '../components/GuardianApp'
import { Phone } from '../components/Phone'
import type { QEvent } from '../lib/api'
import { useEvents } from '../lib/events'
import { useDemo } from '../lib/useDemo'

/** One screen for the pitch: grandmother's bank app, grandson's phone, controls and live log. */
export default function Stage() {
  const demo = useDemo()
  const [events, setEvents] = useState<QEvent[]>([])
  const connected = useEvents((e) => setEvents((xs) => [e, ...xs].slice(0, 80)))

  if (!demo) return <Loading />
  return (
    <div className="mx-auto flex min-h-full max-w-[1500px] flex-wrap items-start justify-center gap-8 p-6">
      <Phone label="Бабушка · приложение банка"><BankApp demo={demo} /></Phone>
      <Phone label="Внук Арман · телефон" tone="dark"><GuardianApp customerId={demo.customer_id} /></Phone>
      <div className="w-[360px] max-w-full space-y-4">
        <div className="rounded-3xl bg-panel p-5 ring-1 ring-line">
          <div className="mb-4 flex items-center justify-between">
            <div className="text-lg font-bold">🛡️ Qorgan · демо</div>
            <span className={`text-xs ${connected ? 'text-emerald-400' : 'text-red-400'}`}>● {connected ? 'live' : 'offline'}</span>
          </div>
          <ControlPanel demo={demo} />
        </div>
        <div className="rounded-3xl bg-panel p-4 ring-1 ring-line">
          <div className="mb-2 text-xs font-semibold uppercase tracking-widest text-slate-400">Что видит Qorgan</div>
          <EventFeed events={events} className="h-[300px]" />
        </div>
      </div>
    </div>
  )
}

export function Loading() {
  return <div className="grid h-full place-items-center text-slate-400">Подключение к Qorgan API…</div>
}
