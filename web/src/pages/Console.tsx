import cytoscape from 'cytoscape'
import { useCallback, useEffect, useRef, useState } from 'react'
import { EventFeed } from '../components/EventFeed'
import { api, kzt, type QEvent, type Transfer } from '../lib/api'
import { useEvents } from '../lib/events'

type Stats = {
  total_transfers: number; transfers: Record<string, number>; prevented_amount: number; held_amount: number
  total_indicators: number; indicators: Record<string, number>; cases: number; schemes: { label: string; count: number }[]
}
type Indicator = { id: string; kind: string; display: string; source: string; hits: number; last_seen: string }

const DECISION: Record<string, string> = {
  allow: 'bg-emerald-500/15 text-emerald-300', challenge: 'bg-sky-500/15 text-sky-300',
  hold: 'bg-amber-500/15 text-amber-300', block: 'bg-red-500/15 text-red-300',
}

/** Bank fraud team / Antifraud Center console. */
export default function Console() {
  const [tab, setTab] = useState<'overview' | 'registry' | 'graph' | 'osint' | 'model'>('overview')
  const [stats, setStats] = useState<Stats | null>(null)
  const [transfers, setTransfers] = useState<Transfer[]>([])
  const [events, setEvents] = useState<QEvent[]>([])

  const refresh = useCallback(() => {
    api<Stats>('/v1/stats').then(setStats).catch(() => {})
    api<Transfer[]>('/v1/transfers', { params: { limit: '30' } }).then(setTransfers).catch(() => {})
  }, [])
  useEffect(() => {
    refresh()
    api<QEvent[]>('/v1/events', { params: { limit: '60' } }).then(setEvents).catch(() => {})
  }, [refresh])
  const live = useEvents((e) => {
    setEvents((xs) => [e, ...xs].slice(0, 120))
    if (/transfer|indicator|case|demo/.test(e.type)) refresh()
  })

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-extrabold">Консоль антифрода</h1>
        <span className={`text-xs ${live ? 'text-emerald-400' : 'text-red-400'}`}>● {live ? 'live' : 'offline'}</span>
        <div className="ml-auto flex gap-1 rounded-xl bg-panel p-1 ring-1 ring-line">
          {([['overview', 'Обзор'], ['registry', 'Реестр'], ['graph', 'Граф связей'], ['osint', 'OSINT'], ['model', 'Модель']] as const).map(([k, l]) => (
            <button key={k} onClick={() => setTab(k)} className={`rounded-lg px-4 py-1.5 text-sm ${tab === k ? 'bg-white/10 font-semibold' : 'text-slate-400'}`}>{l}</button>
          ))}
        </div>
      </div>

      {tab === 'overview' && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi label="Предотвращено" value={kzt(stats?.prevented_amount ?? 0)} accent="text-emerald-400" />
            <Kpi label="На удержании" value={kzt(stats?.held_amount ?? 0)} accent="text-amber-300" />
            <Kpi label="Проверено переводов" value={String(stats?.total_transfers ?? 0)} />
            <Kpi label="Индикаторов в реестре" value={String(stats?.total_indicators ?? 0)} sub={`${stats?.cases ?? 0} диалогов Апы`} />
          </div>
          <div className="grid gap-6 lg:grid-cols-[1fr_420px]">
            <div className="overflow-hidden rounded-3xl bg-panel ring-1 ring-line">
              <div className="border-b border-line px-5 py-3 text-sm font-semibold">Последние переводы</div>
              <div className="max-h-[520px] overflow-y-auto">
                <table className="w-full text-sm">
                  <tbody>
                    {transfers.map((t) => (
                      <tr key={t.id} className="border-b border-line/60 align-top">
                        <td className="px-5 py-3 tabular-nums text-slate-400">{new Date(t.created_at).toLocaleTimeString('ru-RU')}</td>
                        <td className="py-3 font-semibold">{kzt(t.amount)}<div className="font-mono text-xs font-normal text-slate-500">{t.recipient}</div></td>
                        <td className="py-3"><span className={`rounded-md px-2 py-0.5 text-xs font-semibold ${DECISION[t.decision]}`}>{t.decision}</span><div className="mt-1 text-xs text-slate-500">{t.status}</div></td>
                        <td className="py-3 pr-5 text-xs text-slate-300">
                          <div className="mb-1 font-semibold">риск {Math.round(t.score * 100)}%</div>
                          {t.reasons.slice(0, 3).map((r) => <div key={r.code}>• {r.text}</div>)}
                        </td>
                      </tr>
                    ))}
                    {transfers.length === 0 && <tr><td className="p-5 text-slate-500">Переводов пока нет</td></tr>}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="space-y-6">
              <div className="rounded-3xl bg-panel p-5 ring-1 ring-line">
                <div className="mb-3 text-sm font-semibold">Схемы (по диалогам Апы)</div>
                {(stats?.schemes ?? []).filter((s) => s.label !== 'Не определена').map((s) => (
                  <div key={s.label} className="mb-2">
                    <div className="flex justify-between text-xs"><span>{s.label}</span><span className="text-slate-400">{s.count}</span></div>
                    <div className="mt-1 h-1.5 rounded bg-white/5"><div className="h-full rounded bg-shield" style={{ width: `${Math.min(100, s.count * 20)}%` }} /></div>
                  </div>
                ))}
                {!stats?.schemes?.length && <div className="text-xs text-slate-500">Нет данных</div>}
              </div>
              <div className="rounded-3xl bg-panel p-4 ring-1 ring-line">
                <div className="mb-2 text-sm font-semibold">Поток событий</div>
                <EventFeed events={events} className="h-[300px]" />
              </div>
            </div>
          </div>
        </>
      )}
      {tab === 'registry' && <Registry />}
      {tab === 'graph' && <Graph />}
      {tab === 'osint' && <Osint />}
      {tab === 'model' && <ModelCard />}
    </div>
  )
}

function Kpi({ label, value, sub, accent = '' }: { label: string; value: string; sub?: string; accent?: string }) {
  return (
    <div className="rounded-3xl bg-panel p-5 ring-1 ring-line">
      <div className="text-xs uppercase tracking-widest text-slate-400">{label}</div>
      <div className={`mt-2 text-3xl font-extrabold ${accent}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  )
}

function Registry() {
  const [items, setItems] = useState<Indicator[]>([])
  const [value, setValue] = useState('')
  const [check, setCheck] = useState<any>(null)
  const load = () => api<Indicator[]>('/v1/indicators', { params: { limit: '200' } }).then(setItems)
  useEffect(() => { load() }, [])
  const doCheck = async () => setCheck(await api('/v1/check', { params: { value } }).catch((e) => ({ error: e.message })))
  const add = async () => { await api('/v1/indicators', { body: { value, source: 'bank' } }); setValue(''); load() }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="Карта, телефон, IBAN, домен, ссылка, @аккаунт"
          className="min-w-[280px] flex-1 rounded-xl bg-panel px-4 py-2.5 text-sm ring-1 ring-line outline-none" />
        <button onClick={doCheck} className="rounded-xl bg-white/10 px-4 text-sm font-semibold">Проверить</button>
        <button onClick={add} className="rounded-xl bg-shield px-4 text-sm font-semibold text-black">Добавить в реестр</button>
      </div>
      {check && (
        <div className="rounded-2xl bg-panel p-4 text-sm ring-1 ring-line">
          {check.error ? <span className="text-red-300">{check.error}</span> : <>
            <b>{check.display}</b> · {check.verdict} · риск {Math.round((check.score ?? 0) * 100)}%
            <ul className="mt-1 text-slate-300">{(check.reasons ?? []).map((r: string) => <li key={r}>• {r}</li>)}</ul>
          </>}
        </div>
      )}
      <div className="overflow-hidden rounded-3xl bg-panel ring-1 ring-line">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wider text-slate-500"><tr><th className="px-5 py-3">Тип</th><th>Значение</th><th>Источник</th><th>Совпадений</th><th>Последний раз</th></tr></thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.id} className="border-t border-line/60">
                <td className="px-5 py-2.5">{i.kind}</td><td className="font-mono">{i.display}</td><td>{i.source}</td><td>{i.hits}</td>
                <td className="text-slate-400">{new Date(i.last_seen).toLocaleString('ru-RU')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="text-xs text-slate-500">Номера карт и телефонов хранятся только как HMAC-хэш и маска: совпадение ищется без хранения исходных данных.</div>
    </div>
  )
}

const NODE_COLOR: Record<string, string> = { case: '#f59e0b', card: '#ef4444', phone: '#38bdf8', domain: '#a78bfa', url: '#a78bfa', iban: '#f43f5e', account: '#22d3ee' }

function Graph() {
  const ref = useRef<HTMLDivElement>(null)
  const [empty, setEmpty] = useState(false)
  useEffect(() => {
    let cy: cytoscape.Core | undefined
    api('/v1/graph').then((g) => {
      setEmpty(g.nodes.length === 0)
      if (!ref.current) return
      cy = cytoscape({
        container: ref.current,
        elements: [...g.nodes, ...g.edges],
        style: [
          { selector: 'node', style: { label: 'data(label)', color: '#cbd5e1', 'font-size': 10, 'text-valign': 'bottom', 'text-margin-y': 4, width: 22, height: 22, 'background-color': (n: any) => NODE_COLOR[n.data('type')] ?? '#64748b' } },
          { selector: 'node[type="case"]', style: { shape: 'round-rectangle', width: 30, height: 30 } },
          { selector: 'edge', style: { width: 1.5, 'line-color': '#334155', 'curve-style': 'bezier' } },
          { selector: 'edge[type="ct"]', style: { 'line-style': 'dashed', 'line-color': '#7c3aed' } },
        ],
        layout: { name: 'cose', animate: false, padding: 30 },
      })
    })
    return () => cy?.destroy()
  }, [])
  return (
    <div className="rounded-3xl bg-panel p-4 ring-1 ring-line">
      <div className="mb-2 flex flex-wrap gap-4 text-xs text-slate-400">
        {Object.entries({ case: 'диалог Апы', card: 'карта', phone: 'телефон', domain: 'домен', iban: 'IBAN' }).map(([k, l]) => (
          <span key={k}><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full" style={{ background: NODE_COLOR[k] }} />{l}</span>
        ))}
        <span>Общая улика у нескольких диалогов = одна группировка</span>
      </div>
      {empty && <div className="p-10 text-center text-slate-500">Граф пуст: поговорите с Апой, чтобы собрать улики.</div>}
      <div ref={ref} className="h-[600px]" />
    </div>
  )
}

function Osint() {
  const [domain, setDomain] = useState('kaspi-bonus-vyplata.top')
  const [res, setRes] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const run = async (save = false) => {
    setBusy(true)
    setRes(await api('/v1/osint/domain', { body: { domain, save } }).catch((e) => ({ error: e.message })))
    setBusy(false)
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <input value={domain} onChange={(e) => setDomain(e.target.value)} className="min-w-[280px] flex-1 rounded-xl bg-panel px-4 py-2.5 font-mono text-sm ring-1 ring-line outline-none" />
        <button onClick={() => run()} disabled={busy} className="rounded-xl bg-white/10 px-4 text-sm font-semibold">{busy ? '…' : 'Анализ'}</button>
        <button onClick={() => run(true)} disabled={busy} className="rounded-xl bg-shield px-4 text-sm font-semibold text-black">Анализ + в реестр</button>
      </div>
      {res && !res.error && (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-3xl bg-panel p-5 ring-1 ring-line">
            <div className="text-xs uppercase tracking-widest text-slate-400">Вердикт</div>
            <div className={`mt-1 text-3xl font-extrabold ${res.verdict === 'phishing' ? 'text-red-400' : res.verdict === 'suspicious' ? 'text-amber-300' : 'text-emerald-400'}`}>
              {res.verdict} · {Math.round(res.score * 100)}%
            </div>
            {res.imitates && <div className="mt-1 text-sm">Имитирует: <b>{res.imitates}</b></div>}
            <ul className="mt-3 space-y-1 text-sm text-slate-300">{res.reasons.map((r: string) => <li key={r}>• {r}</li>)}</ul>
          </div>
          <div className="space-y-2 rounded-3xl bg-panel p-5 text-sm ring-1 ring-line">
            <div><span className="text-slate-400">Регистрация (RDAP):</span> {res.rdap?.registered ?? '—'} {res.rdap?.registrar ? `· ${res.rdap.registrar}` : ''}</div>
            <div><span className="text-slate-400">Возраст:</span> {res.age_days ?? '—'} дн.</div>
            <div><span className="text-slate-400">IP:</span> {res.ips?.join(', ') || '—'}</div>
            <div><span className="text-slate-400">Сертификаты (CT):</span> {res.ct?.cert_count ?? '—'}</div>
            {res.ct?.names?.length > 0 && <div className="font-mono text-xs text-slate-400">{res.ct.names.slice(0, 15).join('  ')}</div>}
          </div>
        </div>
      )}
      {res?.error && <div className="text-red-300">{res.error}</div>}
    </div>
  )
}

const FEATURE_RU: Record<string, string> = {
  call_active: 'Идёт звонок', unknown_caller: 'Незнакомый номер', call_minutes_log: 'Длительность звонка',
  recent_call_decay: 'Звонок недавно', messenger_call: 'Звонок в мессенджере', telco_risk: 'Флаг оператора',
  recipient_new: 'Новый получатель', amount_ratio_log: 'Сумма к обычной', elderly: 'Клиент 60+',
  hesitation: 'Колебания при вводе', pasted_recipient: 'Реквизиты вставлены', app_switches: 'Переключения приложений',
  night: 'Ночь', remote_control: 'Удалённый доступ / экран', recipient_fan_in_log: 'Получатель-дроп (fan-in)',
}

function ModelCard() {
  const [m, setM] = useState<any>(null)
  useEffect(() => { api('/v1/model').then(setM) }, [])
  if (!m) return null
  const weights = Object.entries(m.weights as Record<string, number>).sort((a, b) => b[1] - a[1])
  const max = Math.max(...weights.map(([, w]) => Math.abs(w)))
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
      <div className="rounded-3xl bg-panel p-6 ring-1 ring-line">
        <div className="mb-4 text-sm font-semibold">Вес каждого сигнала в модели</div>
        <div className="space-y-2">
          {weights.map(([f, w]) => (
            <div key={f} className="grid grid-cols-[200px_1fr_50px] items-center gap-3 text-sm">
              <span className="text-slate-300">{FEATURE_RU[f] ?? f}</span>
              <div className="h-2 rounded bg-white/5"><div className={`h-full rounded ${w >= 0 ? 'bg-shield' : 'bg-sky-400'}`} style={{ width: `${(Math.abs(w) / max) * 100}%` }} /></div>
              <span className="text-right tabular-nums text-slate-400">{w.toFixed(2)}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="space-y-4 rounded-3xl bg-panel p-6 text-sm ring-1 ring-line">
        <div><div className="text-xs uppercase tracking-widest text-slate-400">Версия</div><div className="font-mono">{m.version}</div></div>
        <div><div className="text-xs uppercase tracking-widest text-slate-400">Тип</div>{m.type}</div>
        <div>
          <div className="text-xs uppercase tracking-widest text-slate-400">На отложенной синтетике</div>
          ROC-AUC {m.metrics_on_synthetic_holdout.roc_auc} · PR-AUC {m.metrics_on_synthetic_holdout.pr_auc}
        </div>
        <div className="rounded-xl bg-amber-500/10 p-3 text-xs text-amber-200 ring-1 ring-amber-500/30">
          Метрики на синтетических данных показывают только, что модель выучила заложенные паттерны. Реальная точность
          измеряется на пилоте в теневом режиме на переводах банка.
        </div>
        <div className="text-xs text-slate-400">Поверх модели работают жёсткие правила: реестр мошенников, удалённый доступ во время звонка с незнакомцем, дроп-получатель, обязательный вопрос при переводе новому получателю во время звонка.</div>
      </div>
    </div>
  )
}
