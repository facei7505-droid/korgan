import { BankApp } from '../components/BankApp'
import { GuardianApp } from '../components/GuardianApp'
import { useDemo } from '../lib/useDemo'
import { Loading } from './Stage'

// Full-screen versions to open on real phones over the local network.
export function BankPage() {
  const demo = useDemo()
  return <div className="mx-auto h-full max-w-md bg-slate-50 text-slate-900">{demo ? <BankApp demo={demo} /> : <Loading />}</div>
}

export function GuardianPage() {
  return <div className="mx-auto h-full max-w-md bg-slate-950 text-white"><GuardianApp /></div>
}
