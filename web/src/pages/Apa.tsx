import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'

type Msg = { role: 'scammer' | 'apa'; text: string }
type Found = { kind: string; display: string; new: boolean }

const KIND: Record<string, string> = { card: '💳 Карта', phone: '📱 Телефон', iban: '🏦 IBAN', url: '🔗 Ссылка', domain: '🌐 Домен', account: '👤 Аккаунт' }
const SAMPLES = [
  'Здравствуйте, это служба безопасности банка. По вашей карте подозрительная операция, на вас оформляют кредит.',
  'Чтобы сохранить деньги, переведите их на безопасный счёт 4400 4312 3412 3417. Срочно, иначе всё заблокируют.',
  'Скажите код из смс, который сейчас придёт. И установите приложение по ссылке https://kaspi-support-secure.top/app',
  'Мой номер для связи +7 707 555 01 99, следователь Ахметов, отдел финансовых расследований.',
]

/** Play the scammer, watch Apa keep you talking and pull your details into the registry. */
export default function Apa() {
  const [conv] = useState(() => `web:${Math.random().toString(36).slice(2, 8)}`)
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [found, setFound] = useState<Found[]>([])
  const [scheme, setScheme] = useState<string>('')
  const [engine, setEngine] = useState('')
  const [text, setText] = useState('')
  const [typing, setTyping] = useState(false)
  const end = useRef<HTMLDivElement>(null)

  useEffect(() => end.current?.scrollIntoView({ behavior: 'smooth' }), [msgs, typing])

  const send = async (t = text) => {
    if (!t.trim()) return
    setText('')
    setMsgs((m) => [...m, { role: 'scammer', text: t }])
    setTyping(true)
    try {
      const r = await api('/v1/apa/message', { body: { conversation_id: conv, channel: 'web', text: t } })
      await new Promise((ok) => setTimeout(ok, 700))
      setMsgs((m) => [...m, { role: 'apa', text: r.reply }])
      setFound((f) => [...r.extracted.filter((x: Found) => !f.some((y) => y.display === x.display)), ...f])
      setScheme(r.scheme)
      setEngine(r.engine)
    } finally {
      setTyping(false)
    }
  }

  return (
    <div className="mx-auto grid h-full max-w-6xl gap-6 p-6 lg:grid-cols-[1fr_360px]">
      <div className="flex min-h-[600px] flex-col overflow-hidden rounded-3xl bg-[#0e1621] ring-1 ring-line">
        <div className="flex items-center gap-3 border-b border-white/5 bg-[#17212b] px-5 py-3">
          <div className="grid h-10 w-10 place-items-center rounded-full bg-amber-200 text-xl">👵</div>
          <div>
            <div className="font-semibold">Бибигуль апа</div>
            <div className="text-xs text-sky-300">{typing ? 'печатает…' : 'в сети'}</div>
          </div>
          <div className="ml-auto text-right text-[11px] text-slate-500">Вы играете мошенника<br />{engine && `движок: ${engine}`}</div>
        </div>
        <div className="flex-1 space-y-2 overflow-y-auto p-5">
          {msgs.length === 0 && <div className="mt-10 text-center text-sm text-slate-500">Напишите апашке как мошенник, или выберите готовую фразу ниже.</div>}
          {msgs.map((m, i) => (
            <div key={i} className={`flex ${m.role === 'scammer' ? 'justify-end' : ''}`}>
              <div className={`max-w-[75%] rounded-2xl px-4 py-2 text-sm leading-relaxed animate-pop ${m.role === 'scammer' ? 'rounded-br-sm bg-[#2b5278]' : 'rounded-bl-sm bg-[#182533]'}`}>{m.text}</div>
            </div>
          ))}
          <div ref={end} />
        </div>
        <div className="flex flex-wrap gap-2 px-4 pb-2">
          {SAMPLES.map((s, i) => (
            <button key={i} onClick={() => send(s)} className="rounded-full bg-white/5 px-3 py-1 text-xs text-slate-300 ring-1 ring-white/10 hover:bg-white/10">Фраза {i + 1}</button>
          ))}
        </div>
        <form onSubmit={(e) => { e.preventDefault(); send() }} className="flex gap-2 border-t border-white/5 bg-[#17212b] p-3">
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Сообщение…" className="flex-1 rounded-xl bg-[#0e1621] px-4 py-2.5 text-sm outline-none" />
          <button className="rounded-xl bg-sky-600 px-5 text-sm font-semibold">➤</button>
        </form>
      </div>

      <div className="space-y-4">
        <div className="rounded-3xl bg-panel p-5 ring-1 ring-line">
          <div className="text-xs font-semibold uppercase tracking-widest text-slate-400">Схема</div>
          <div className="mt-1 text-lg font-bold">{scheme && scheme !== 'unknown' ? schemeLabel(scheme) : '—'}</div>
        </div>
        <div className="rounded-3xl bg-panel p-5 ring-1 ring-line">
          <div className="mb-3 text-xs font-semibold uppercase tracking-widest text-slate-400">Улики → реестр банков</div>
          {found.length === 0 && <div className="text-sm text-slate-500">Пока ничего. Апа выведет мошенника на реквизиты.</div>}
          <div className="space-y-2">
            {found.map((f) => (
              <div key={f.display} className="animate-pop rounded-xl bg-red-500/10 p-3 ring-1 ring-red-500/30">
                <div className="text-xs text-red-300">{KIND[f.kind] ?? f.kind} {f.new ? '· новый' : '· уже в базе'}</div>
                <div className="font-mono text-sm">{f.display}</div>
              </div>
            ))}
          </div>
          {found.some((f) => f.kind === 'card') && (
            <div className="mt-3 text-xs text-emerald-300">Перевод на эту карту в любом подключённом банке теперь будет остановлен.</div>
          )}
        </div>
      </div>
    </div>
  )
}

function schemeLabel(s: string) {
  return ({
    fake_bank_security: '«Служба безопасности банка»', fake_police: '«Полиция / КНБ»', relative_in_trouble: '«Родственник в беде»',
    sms_code: 'Выманивание SMS-кода', investment: 'Фейковые инвестиции', prize_or_payout: '«Выигрыш / выплата»',
    marketplace: 'Маркетплейс', drop_recruitment: 'Вербовка дропов',
  } as Record<string, string>)[s] ?? s
}
