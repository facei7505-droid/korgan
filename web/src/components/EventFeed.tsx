import { kzt, type QEvent } from '../lib/api'

const ICON: Record<string, string> = {
  'call.started': '📞', 'call.ended': '📴', 'transfer.scored': '💸', 'transfer.updated': '🔁', 'guardian.alert': '👦',
  'indicator.new': '🧷', 'indicator.seen': '🔂', 'apa.turn': '🧓', 'case.opened': '📂', 'report.received': '📨',
  'guardian.linked': '🔗', 'demo.reset': '♻️',
}

export function describe(e: QEvent): string {
  const p = e.payload ?? {}
  switch (e.type) {
    case 'call.started': return `Звонок: ${p.channel}, ${p.in_contacts ? 'контакт' : 'незнакомый номер'}${p.spoof_suspected ? ', подмена номера' : ''}`
    case 'call.ended': return 'Звонок завершён'
    case 'transfer.scored': return `${kzt(p.amount)} → ${p.recipient}: ${p.decision.toUpperCase()} (риск ${Math.round(p.score * 100)}%)`
    case 'transfer.updated': return `Перевод ${p.id}: ${p.status}${p.resolution ? ` (${p.resolution})` : ''}`
    case 'guardian.alert': return `Пуш доверенному лицу: ${p.guardian_name}`
    case 'indicator.new': return `Новый индикатор ${p.kind}: ${p.display} [${p.source}]`
    case 'indicator.seen': return `Повтор ${p.kind}: ${p.display} (×${p.hits})`
    case 'apa.turn': return `Апа: «${String(p.apa).slice(0, 60)}»`
    case 'case.opened': return `Новый диалог с мошенником (${p.channel})`
    case 'report.received': return `Жалоба: ${p.verdict}${p.scheme ? `, ${p.scheme}` : ''}`
    case 'guardian.linked': return `${p.name} подключил Telegram`
    case 'demo.reset': return 'Демо сброшено'
    default: return e.type
  }
}

export function EventFeed({ events, className = '' }: { events: QEvent[]; className?: string }) {
  return (
    <div className={`space-y-1 overflow-y-auto font-mono text-[12px] ${className}`}>
      {events.length === 0 && <div className="text-slate-500">Ожидание событий…</div>}
      {events.map((e) => (
        <div key={e.id} className="animate-pop flex gap-2 rounded-lg px-2 py-1 hover:bg-white/5">
          <span className="text-slate-500 tabular-nums">{new Date(e.created_at).toLocaleTimeString('ru-RU')}</span>
          <span>{ICON[e.type] ?? '•'}</span>
          <span className={e.type === 'guardian.alert' || (e.type === 'transfer.scored' && e.payload.decision !== 'allow') ? 'text-amber-300' : 'text-slate-200'}>{describe(e)}</span>
        </div>
      ))}
    </div>
  )
}
