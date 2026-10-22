import { Link } from 'react-router-dom'

const CARDS = [
  { to: '/stage', icon: '🎬', title: 'Сцена демо', text: 'Телефон бабушки, телефон внука и пульт на одном экране. Для питча.' },
  { to: '/console', icon: '📊', title: 'Консоль антифрода', text: 'Переводы, причины решений, реестр, граф группировок, OSINT доменов.' },
  { to: '/apa', icon: '👵', title: 'Апа.AI', text: 'Сыграйте мошенника. Апа удерживает вас и вытягивает реквизиты в реестр.' },
  { to: '/bank', icon: '📱', title: 'Приложение банка', text: 'Откройте на реальном телефоне в той же сети.' },
  { to: '/guardian', icon: '👦', title: 'Телефон внука', text: 'Пуш доверенному человеку в реальном времени.' },
]

export default function Home() {
  return (
    <div className="mx-auto max-w-5xl px-6 py-14">
      <div className="text-sm font-semibold uppercase tracking-[.3em] text-shield">Qorgan · Қорған</div>
      <h1 className="mt-3 text-4xl font-extrabold leading-tight sm:text-5xl">Банк видит перевод, но не видит,<br />что клиенту сейчас диктуют.<br /><span className="text-shield">Мы видим.</span></h1>
      <p className="mt-5 max-w-2xl text-lg text-slate-300">
        Qorgan соединяет сигнал звонка (оператор и телефон), поведение в банковском приложении и разведданные Апа.AI о картах дропов
        в один риск-скор. Перевод мошеннику ставится на паузу, клиенту задаётся правильный вопрос, а доверенный человек получает пуш.
      </p>
      <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {CARDS.map((c) => (
          <Link key={c.to} to={c.to} className="group rounded-3xl bg-panel p-6 ring-1 ring-line transition hover:-translate-y-0.5 hover:ring-shield/50">
            <div className="text-3xl">{c.icon}</div>
            <div className="mt-3 text-lg font-bold group-hover:text-shield">{c.title}</div>
            <div className="mt-1 text-sm text-slate-400">{c.text}</div>
          </Link>
        ))}
      </div>
    </div>
  )
}
