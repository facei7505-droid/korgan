import { useState } from 'react'
import { api, type DemoInfo } from '../lib/api'

/** Stage controls: simulate what the phone OS / telecom operator reports to the bank. */
export function ControlPanel({ demo }: { demo: DemoInfo }) {
  const [callId, setCallId] = useState<string | null>(null)
  const [copied, setCopied] = useState('')

  const start = async (body: object) => {
    if (callId) await api(`/v1/signals/call/${callId}/end`, { method: 'POST' }).catch(() => {})
    const c = await api('/v1/signals/call', { body: { customer_id: demo.customer_id, ...body } })
    setCallId(c.id)
  }
  const end = async () => {
    if (!callId) return
    await api(`/v1/signals/call/${callId}/end`, { method: 'POST' })
    setCallId(null)
  }
  const reset = async () => {
    await api('/v1/demo/reset', { method: 'POST' })
    setCallId(null)
  }
  const copy = (label: string, v: string) => {
    navigator.clipboard?.writeText(v)
    setCopied(label)
    setTimeout(() => setCopied(''), 1200)
  }

  const btn = 'w-full rounded-xl px-3 py-2.5 text-left text-sm font-medium ring-1 transition active:scale-[.98]'
  return (
    <div className="space-y-4">
      <div>
        <div className="mb-2 text-xs font-semibold uppercase tracking-widest text-slate-400">Сигнал звонка (ОС / оператор)</div>
        <div className="space-y-2">
          <button className={`${btn} bg-red-500/15 text-red-200 ring-red-500/30 hover:bg-red-500/25`}
            onClick={() => start({ channel: 'whatsapp', counterparty: '+77075550199', in_contacts: false })}>
            📞 «Служба безопасности» звонит в WhatsApp
          </button>
          <button className={`${btn} bg-red-500/15 text-red-200 ring-red-500/30 hover:bg-red-500/25`}
            onClick={() => start({ source: 'telco', channel: 'cellular', counterparty: demo.scam_phone, in_contacts: false, spoof_suspected: true })}>
            📡 Оператор: номер из базы Апы, подмена номера
          </button>
          <button className={`${btn} bg-white/5 text-slate-200 ring-white/10 hover:bg-white/10`}
            onClick={() => start({ channel: 'cellular', counterparty: '+77014564455', in_contacts: true })}>
            👦 Звонит внук (контакт)
          </button>
          <button disabled={!callId} className={`${btn} bg-white/5 text-slate-300 ring-white/10 disabled:opacity-30`} onClick={end}>📴 Завершить звонок</button>
        </div>
      </div>
      <div>
        <div className="mb-2 text-xs font-semibold uppercase tracking-widest text-slate-400">Реквизиты для демо (клик = копировать)</div>
        <div className="space-y-1.5 text-xs">
          {[
            ['Новая карта «безопасного счёта»', '4400 4312 3412 3417'],
            ['Карта дропа из базы Апы', demo.drop_card.replace(/(\d{4})(?=\d)/g, '$1 ')],
            ['Фишинговый домен', demo.phishing_domain],
          ].map(([l, v]) => (
            <button key={l} onClick={() => copy(l, v)} className="flex w-full justify-between gap-2 rounded-lg bg-white/5 px-3 py-2 text-left ring-1 ring-white/10 hover:bg-white/10">
              <span className="text-slate-400">{l}</span>
              <span className="font-mono text-slate-100">{copied === l ? 'скопировано ✓' : v}</span>
            </button>
          ))}
        </div>
      </div>
      <button onClick={reset} className="text-xs text-slate-500 underline-offset-4 hover:underline">♻️ Сбросить демо</button>
    </div>
  )
}
