import type { ReactNode } from 'react'

export function Phone({ children, label, tone = 'light' }: { children: ReactNode; label?: string; tone?: 'light' | 'dark' }) {
  return (
    <div className="flex flex-col items-center gap-3">
      {label && <div className="text-xs font-semibold uppercase tracking-widest text-slate-400">{label}</div>}
      <div className="relative h-[720px] w-[360px] max-w-full rounded-[3rem] border-[10px] border-slate-800 bg-slate-900 shadow-2xl shadow-black/60">
        <div className="absolute left-1/2 top-2 z-20 h-6 w-28 -translate-x-1/2 rounded-full bg-black" />
        <div className={`h-full w-full overflow-hidden rounded-[2.3rem] ${tone === 'light' ? 'bg-slate-50 text-slate-900' : 'bg-slate-950 text-white'}`}>
          {children}
        </div>
      </div>
    </div>
  )
}
