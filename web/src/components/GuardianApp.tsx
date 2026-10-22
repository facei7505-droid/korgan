import { useState } from 'react'
import { api, CHANNEL_LABEL, kzt, type Reason } from '../lib/api'
import { chime, useEvents } from '../lib/events'

type Alert = {
  transfer_id: string; customer_name: string; amount: number; recipient: string; score: number
  decision: string; reasons: Reason[]; call: { active: boolean; channel: string; minutes: number; in_contacts: boolean } | null
  status?: string
}

export function GuardianApp() {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [open, setOpen] = useState<string | null>(null)
  const now = new Date()

  useEvents((e) => {
    if (e.type === 'guardian.alert') {
      setAlerts((a) => [e.payload, ...a.filter((x) => x.transfer_id !== e.payload.transfer_id)])
      setOpen(e.payload.transfer_id)
      chime()
    }
    if (e.type === 'transfer.updated') setAlerts((a) => a.map((x) => (x.transfer_id === e.payload.id ? { ...x, status: e.payload.status } : x)))
    if (e.type === 'demo.reset') { setAlerts([]); setOpen(null) }
  })

  const decide = async (id: string, approve: boolean) => {
    const t = await api(`/v1/transfers/${id}/guardian`, { body: { approve } }).catch(() => null)
    if (t) setAlerts((a) => a.map((x) => (x.transfer_id === id ? { ...x, status: t.status } : x)))
  }

  const current = alerts.find((a) => a.transfer_id === open)

  return (
    <div className="relative flex h-full flex-col bg-gradient-to-b from-indigo-950 via-slate-900 to-black px-4 pt-14">
      <div className="text-center">
        <div className="text-6xl font-light tabular-nums">{now.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</div>
        <div className="text-sm text-slate-300">{now.toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' })}</div>
      </div>
      <div className="mt-8 space-y-2">
        {alerts.length === 0 && <div className="text-center text-xs text-slate-500">Телефон Армана · уведомлений нет</div>}
        {alerts.map((a) => (
          <button key={a.transfer_id} onClick={() => setOpen(a.transfer_id)} className="animate-pop w-full rounded-2xl bg-white/15 p-3 text-left backdrop-blur ring-1 ring-white/10">
            <div className="flex items-center gap-2 text-[11px] text-slate-300"><span>🛡️</span> QORGAN · сейчас</div>
            <div className="mt-1 text-sm font-semibold">⚠️ {a.customer_name.split(' ')[0]} переводит {kzt(a.amount)}</div>
            <div className="text-xs text-slate-300">
              {a.status === 'cancelled' ? 'Перевод остановлен' : a.status === 'released' ? 'Вы разрешили перевод' :
                a.call ? `Во время звонка с незнакомым номером (${CHANNEL_LABEL[a.call.channel]}, ${a.call.minutes} мин)` : 'Перевод приостановлен'}
            </div>
          </button>
        ))}
      </div>

      {current && (
        <div className="absolute inset-0 z-10 flex flex-col bg-slate-950/95 px-5 pb-6 pt-12 animate-pop">
          <button onClick={() => setOpen(null)} className="self-end text-sm text-slate-400">Закрыть</button>
          <div className="mt-2 text-xs font-semibold uppercase tracking-widest text-amber-400">Требуется ваше решение</div>
          <div className="mt-2 text-2xl font-extrabold leading-tight">{current.customer_name} пытается перевести {kzt(current.amount)}</div>
          {current.call && (
            <div className="mt-3 rounded-2xl bg-red-500/15 p-3 text-sm text-red-200 ring-1 ring-red-500/30">
              📞 Прямо {current.call.active ? 'сейчас' : 'перед этим'} она говорит с {current.call.in_contacts ? 'контактом' : 'незнакомым номером'} через {CHANNEL_LABEL[current.call.channel]} {current.call.minutes < 1 ? 'меньше минуты' : `уже ${Math.round(current.call.minutes)} мин`}
            </div>
          )}
          <ul className="mt-3 space-y-1 text-sm text-slate-300">{current.reasons.map((r) => <li key={r.code}>• {r.text}</li>)}</ul>
          <div className="mt-2 text-xs text-slate-500">Получатель: {current.recipient} · риск {Math.round(current.score * 100)}%</div>
          <div className="mt-auto grid gap-3">
            {current.status === 'cancelled' ? <div className="rounded-2xl bg-emerald-600/20 p-4 text-center font-semibold text-emerald-300">✅ Перевод остановлен. Позвоните бабушке.</div>
              : current.status === 'released' ? <div className="rounded-2xl bg-white/10 p-4 text-center">Перевод разрешён</div>
              : <>
                <a href="tel:" className="rounded-2xl bg-white/10 py-3 text-center font-semibold">📞 Позвонить бабушке</a>
                <button onClick={() => decide(current.transfer_id, false)} className="rounded-2xl bg-red-600 py-4 font-bold">⛔ Остановить перевод</button>
                <button onClick={() => decide(current.transfer_id, true)} className="rounded-2xl bg-white/10 py-3 text-sm text-slate-300">Я проверил, это она. Разрешить</button>
              </>}
          </div>
        </div>
      )}
    </div>
  )
}
