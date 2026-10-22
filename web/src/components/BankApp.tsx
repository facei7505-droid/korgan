import { useEffect, useRef, useState } from 'react'
import { api, CHANNEL_LABEL, kzt, type CallInfo, type DemoInfo, type Reason, type Transfer } from '../lib/api'
import { useEvents } from '../lib/events'

type ScoreResponse = {
  transfer: Transfer
  call: CallInfo | null
  customer_message: { title: string; body: string } | null
  guardians_notified: string[]
}
type ActiveCall = { id: string; channel: string; counterparty: string | null; in_contacts: boolean; started_at: string }

const fmtCard = (v: string) => v.replace(/\D/g, '').slice(0, 19).replace(/(\d{4})(?=\d)/g, '$1 ')

/** Collects the behavioural signals the bank app would send with the transfer. */
function useBehavior() {
  const s = useRef({ start: Date.now(), last: 0, maxPause: 0, corrections: 0, pasted: false, switches: 0 })
  useEffect(() => {
    const away = () => { if (document.visibilityState === 'hidden') s.current.switches++ }
    const blur = () => s.current.switches++
    document.addEventListener('visibilitychange', away)
    window.addEventListener('blur', blur)
    return () => { document.removeEventListener('visibilitychange', away); window.removeEventListener('blur', blur) }
  }, [])
  return {
    reset() { s.current = { start: Date.now(), last: 0, maxPause: 0, corrections: 0, pasted: false, switches: 0 } },
    key(e: React.KeyboardEvent) {
      const now = Date.now()
      if (s.current.last) s.current.maxPause = Math.max(s.current.maxPause, now - s.current.last)
      s.current.last = now
      if (e.key === 'Backspace' || e.key === 'Delete') s.current.corrections++
    },
    paste() { s.current.pasted = true },
    snapshot() {
      const c = s.current
      return { max_pause_ms: c.maxPause, corrections: c.corrections, session_seconds: (Date.now() - c.start) / 1000, pasted_recipient: c.pasted, app_switches: c.switches }
    },
  }
}

export function BankApp({ demo }: { demo: DemoInfo }) {
  const [screen, setScreen] = useState<'home' | 'transfer' | 'result'>('home')
  const [card, setCard] = useState('')
  const [amount, setAmount] = useState('')
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<ScoreResponse | null>(null)
  const [call, setCall] = useState<ActiveCall | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [err, setErr] = useState('')
  const beh = useBehavior()

  useEffect(() => {
    api<any[]>(`/v1/customers/${demo.customer_id}/calls`).then((calls) => setCall(calls.find((c) => !c.ended_at) ?? null)).catch(() => {})
  }, [demo.customer_id])

  useEffect(() => {
    if (!call) return
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - new Date(call.started_at).getTime()) / 1000)), 1000)
    return () => clearInterval(t)
  }, [call])

  useEvents((e) => {
    if (e.payload?.customer_id !== demo.customer_id && e.type !== 'demo.reset') return
    if (e.type === 'call.started') setCall(e.payload)
    if (e.type === 'call.ended') setCall((c) => (c?.id === e.payload.id ? null : c))
    if (e.type === 'demo.reset') { setCall(null); setScreen('home'); setRes(null) }
    if (e.type === 'transfer.updated') setRes((r) => (r && r.transfer.id === e.payload.id ? { ...r, transfer: { ...r.transfer, ...e.payload } } : r))
  })

  const openTransfer = (prefill?: string) => {
    beh.reset()
    setCard(prefill ? fmtCard(prefill) : '')
    setSaved(Boolean(prefill))
    setAmount('')
    setErr('')
    setScreen('transfer')
  }

  const submit = async () => {
    setBusy(true)
    setErr('')
    try {
      const r = await api<ScoreResponse>('/v1/transfers/score', {
        body: {
          customer_id: demo.customer_id,
          amount: Number(amount.replace(/\D/g, '')),
          recipient: { kind: 'card', value: card },
          behavior: { ...beh.snapshot(), pasted_recipient: beh.snapshot().pasted_recipient && !saved },
        },
      })
      setRes(r)
      setScreen('result')
    } catch (e: any) {
      setErr(e.status === 422 ? 'Проверьте номер карты' : 'Нет связи с сервером')
    } finally {
      setBusy(false)
    }
  }

  const answer = async (dictated: boolean) => {
    if (!res) return
    const t = await api<Transfer>(`/v1/transfers/${res.transfer.id}/challenge`, { body: { dictated } })
    setRes({ ...res, transfer: t })
  }
  const cancel = async () => {
    if (!res) return
    const t = await api<Transfer>(`/v1/transfers/${res.transfer.id}/cancel`, { method: 'POST' })
    setRes({ ...res, transfer: t })
  }

  const mm = `${String(Math.floor(elapsed / 60)).padStart(2, '0')}:${String(elapsed % 60).padStart(2, '0')}`

  return (
    <div className="flex h-full flex-col">
      <div className="h-9 shrink-0" />
      {call && (
        <div className="mx-3 mb-1 flex items-center gap-2 rounded-full bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white">
          <span className="animate-ring">📞</span>
          <span className="truncate">{CHANNEL_LABEL[call.channel] ?? 'Звонок'} · {call.in_contacts ? 'контакт' : call.counterparty ?? 'неизвестный номер'}</span>
          <span className="ml-auto tabular-nums">{mm}</span>
        </div>
      )}

      {screen === 'home' && (
        <div className="flex flex-1 flex-col gap-4 overflow-y-auto px-5 pb-6">
          <div className="flex items-center justify-between pt-2">
            <div>
              <div className="text-xs text-slate-500">Сәлеметсіз бе,</div>
              <div className="text-lg font-bold">Бибигуль</div>
            </div>
            <div className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700">🛡️ Qorgan включён</div>
          </div>
          <div className="rounded-3xl bg-gradient-to-br from-slate-900 to-slate-700 p-5 text-white shadow-lg">
            <div className="text-xs opacity-70">Пенсионная карта</div>
            <div className="mt-1 text-3xl font-extrabold tracking-tight">1 245 300 ₸</div>
            <div className="mt-6 text-xs tracking-widest opacity-60">•••• 4471</div>
          </div>
          <div className="grid grid-cols-3 gap-3 text-center text-xs font-medium">
            <button onClick={() => openTransfer()} className="rounded-2xl bg-white p-3 shadow-sm ring-1 ring-slate-200 active:scale-95">💸<br />Перевод</button>
            <div className="rounded-2xl bg-white p-3 text-slate-400 shadow-sm ring-1 ring-slate-200">🧾<br />Платежи</div>
            <div className="rounded-2xl bg-white p-3 text-slate-400 shadow-sm ring-1 ring-slate-200">🏦<br />Кредиты</div>
          </div>
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Избранное</div>
            <button onClick={() => openTransfer(demo.family_card)} className="flex w-full items-center gap-3 rounded-2xl bg-white p-3 text-left shadow-sm ring-1 ring-slate-200 active:scale-[.98]">
              <div className="grid h-10 w-10 place-items-center rounded-full bg-sky-100 text-lg">👦</div>
              <div><div className="text-sm font-semibold">Арман (внук)</div><div className="text-xs text-slate-500">•••• {demo.family_card.slice(-4)}</div></div>
            </button>
          </div>
        </div>
      )}

      {screen === 'transfer' && (
        <div className="flex flex-1 flex-col gap-4 px-5 pb-6">
          <button onClick={() => setScreen('home')} className="self-start pt-2 text-sm text-slate-500">← Назад</button>
          <div className="text-xl font-bold">Перевод на карту</div>
          <label className="text-xs font-medium text-slate-500">Номер карты получателя
            <input
              inputMode="numeric" value={card} placeholder="0000 0000 0000 0000"
              onKeyDown={beh.key} onPaste={beh.paste}
              onChange={(e) => { setCard(fmtCard(e.target.value)); setSaved(false) }}
              className="mt-1 w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-lg tracking-wider text-slate-900 outline-none focus:border-emerald-500"
            />
          </label>
          <label className="text-xs font-medium text-slate-500">Сумма
            <input
              inputMode="numeric" value={amount} placeholder="0 ₸" onKeyDown={beh.key}
              onChange={(e) => setAmount(new Intl.NumberFormat('ru-RU').format(Number(e.target.value.replace(/\D/g, '') || 0)).replace(/^0$/, ''))}
              className="mt-1 w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-2xl font-bold text-slate-900 outline-none focus:border-emerald-500"
            />
          </label>
          {err && <div className="text-sm text-red-600">{err}</div>}
          <button disabled={busy || card.replace(/\D/g, '').length < 16 || !amount} onClick={submit}
            className="mt-auto rounded-2xl bg-emerald-600 py-4 text-base font-bold text-white disabled:opacity-40 active:scale-[.98]">
            {busy ? 'Проверяем…' : 'Перевести'}
          </button>
        </div>
      )}

      {screen === 'result' && res && <Result res={res} onAnswer={answer} onCancel={cancel} onDone={() => setScreen('home')} />}
    </div>
  )
}

function Reasons({ reasons }: { reasons: Reason[] }) {
  if (!reasons.length) return null
  return (
    <div className="rounded-2xl bg-white/70 p-3 text-left text-xs ring-1 ring-black/5">
      <div className="mb-1 font-semibold text-slate-700">Почему мы остановили:</div>
      <ul className="space-y-1 text-slate-600">{reasons.slice(0, 4).map((r) => <li key={r.code}>• {r.text}</li>)}</ul>
    </div>
  )
}

function Countdown({ until }: { until: string }) {
  const [left, setLeft] = useState(0)
  useEffect(() => {
    const tick = () => setLeft(Math.max(0, Math.floor((new Date(until).getTime() - Date.now()) / 1000)))
    tick()
    const t = setInterval(tick, 1000)
    return () => clearInterval(t)
  }, [until])
  return <span className="tabular-nums">{Math.floor(left / 60)}:{String(left % 60).padStart(2, '0')}</span>
}

function Result({ res, onAnswer, onCancel, onDone }: { res: ScoreResponse; onAnswer: (d: boolean) => void; onCancel: () => void; onDone: () => void }) {
  const t = res.transfer
  const done = (
    <button onClick={onDone} className="mt-auto w-full rounded-2xl bg-slate-900 py-4 font-bold text-white">На главную</button>
  )

  if (t.status === 'completed' || t.status === 'released')
    return (
      <div className="flex flex-1 flex-col items-center gap-3 px-6 pb-6 pt-16 text-center">
        <div className="grid h-20 w-20 place-items-center rounded-full bg-emerald-100 text-4xl">✓</div>
        <div className="text-2xl font-bold">{kzt(t.amount)}</div>
        <div className="text-slate-500">Перевод выполнен · {t.recipient}</div>
        {t.status === 'released' && <div className="text-xs text-slate-500">Доверенный человек подтвердил перевод</div>}
        {done}
      </div>
    )

  if (t.status === 'cancelled')
    return (
      <div className="flex flex-1 flex-col items-center gap-3 px-6 pb-6 pt-14 text-center">
        <div className="grid h-20 w-20 place-items-center rounded-full bg-emerald-100 text-4xl">🛡️</div>
        <div className="text-xl font-bold">Деньги остались у вас</div>
        <div className="text-sm text-slate-600">
          {t.resolution === 'guardian_rejected' ? 'Арман остановил перевод и сейчас вам позвонит.' : 'Перевод отменён.'}
        </div>
        <div className="rounded-2xl bg-amber-50 p-4 text-left text-sm text-amber-900 ring-1 ring-amber-200">
          Положите трубку. Сотрудники банка и полиции никогда не просят переводить деньги, называть коды из SMS или устанавливать приложения.
        </div>
        {done}
      </div>
    )

  if (t.status === 'pending_challenge')
    return (
      <div className="flex flex-1 flex-col gap-4 bg-amber-50 px-6 pb-6 pt-10">
        <div className="text-5xl">✋</div>
        <div className="text-2xl font-extrabold leading-tight text-amber-950">{res.customer_message?.title}</div>
        <div className="text-sm text-amber-900">{res.customer_message?.body}</div>
        <Reasons reasons={t.reasons} />
        <div className="mt-auto grid gap-3">
          <button onClick={() => onAnswer(true)} className="rounded-2xl bg-red-600 py-4 font-bold text-white">Да, мне подсказывают по телефону</button>
          <button onClick={() => onAnswer(false)} className="rounded-2xl bg-white py-4 font-semibold text-slate-700 ring-1 ring-slate-300">Нет, я перевожу сам(а)</button>
        </div>
      </div>
    )

  // held: hold or block
  const block = t.decision === 'block'
  return (
    <div className={`flex flex-1 flex-col gap-4 px-6 pb-6 pt-10 ${block ? 'bg-red-50' : 'bg-amber-50'}`}>
      <div className="text-5xl">{block ? '⛔' : '⏸️'}</div>
      <div className={`text-2xl font-extrabold leading-tight ${block ? 'text-red-950' : 'text-amber-950'}`}>{res.customer_message?.title}</div>
      {!block && t.hold_until && (
        <div className="text-4xl font-black text-amber-700"><Countdown until={t.hold_until} /></div>
      )}
      <div className={`text-sm ${block ? 'text-red-900' : 'text-amber-900'}`}>{res.customer_message?.body}</div>
      <Reasons reasons={t.reasons} />
      {res.guardians_notified.length > 0 && (
        <div className="flex items-center gap-2 rounded-2xl bg-white p-3 text-sm ring-1 ring-black/5">
          <span className="text-xl">👦</span> Арман получил уведомление
          {t.resolution === 'guardian_approved_pending_bank_review' && <span className="ml-auto text-xs text-slate-500">ждём проверку банка</span>}
        </div>
      )}
      <button onClick={onCancel} className="mt-auto rounded-2xl bg-slate-900 py-4 font-bold text-white">Отменить перевод</button>
    </div>
  )
}
