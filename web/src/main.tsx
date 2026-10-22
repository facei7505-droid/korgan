import { lazy, StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Link, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import './index.css'
import Apa from './pages/Apa'
import Home from './pages/Home'
import { BankPage, GuardianPage } from './pages/Single'
import Stage from './pages/Stage'

const Console = lazy(() => import('./pages/Console'))

function Shell() {
  const { pathname } = useLocation()
  const bare = pathname === '/bank' || pathname === '/guardian'
  return (
    <div className="flex h-full flex-col">
      {!bare && (
        <nav className="flex items-center gap-1 border-b border-line px-6 py-3 text-sm">
          <Link to="/" className="mr-4 font-extrabold">🛡️ Qorgan</Link>
          {[['/stage', 'Сцена'], ['/console', 'Консоль'], ['/apa', 'Апа.AI']].map(([to, l]) => (
            <NavLink key={to} to={to} className={({ isActive }) => `rounded-lg px-3 py-1.5 ${isActive ? 'bg-white/10 font-semibold' : 'text-slate-400 hover:text-white'}`}>{l}</NavLink>
          ))}
        </nav>
      )}
      <main className="flex-1 overflow-auto">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/stage" element={<Stage />} />
          <Route path="/console" element={<Suspense fallback={null}><Console /></Suspense>} />
          <Route path="/apa" element={<Apa />} />
          <Route path="/bank" element={<BankPage />} />
          <Route path="/guardian" element={<GuardianPage />} />
        </Routes>
      </main>
    </div>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter><Shell /></BrowserRouter>
  </StrictMode>,
)
