// The bank app, guardian phone and console all talk to the Risk API directly.
// In production the bank's backend calls the API server-to-server and the key never reaches a browser.
export const API_URL: string =
  import.meta.env.VITE_API_URL || `${location.protocol}//${location.hostname}:8000`
export const API_KEY: string = import.meta.env.VITE_API_KEY || 'dev-admin-key'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function api<T = any>(
  path: string,
  opts: { method?: string; body?: unknown; params?: Record<string, string>; headers?: Record<string, string> } = {},
): Promise<T> {
  const url = new URL(API_URL + path)
  Object.entries(opts.params ?? {}).forEach(([k, v]) => url.searchParams.set(k, v))
  const res = await fetch(url, {
    method: opts.method ?? (opts.body ? 'POST' : 'GET'),
    headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY, ...opts.headers },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  })
  if (!res.ok) throw new ApiError(res.status, (await res.text()) || res.statusText)
  return res.json()
}

export const kzt = (n: number) => new Intl.NumberFormat('ru-RU').format(Math.round(n)) + ' ₸'

export type Reason = { code: string; text: string; weight: number }
export type Transfer = {
  id: string; customer_id: string; amount: number; recipient: string; score: number
  decision: 'allow' | 'challenge' | 'hold' | 'block'
  status: 'completed' | 'pending_challenge' | 'held' | 'cancelled' | 'released'
  reasons: Reason[]; hold_until: string | null; resolution: string | null; created_at: string
}
export type CallInfo = { active: boolean; channel: string; minutes: number; in_contacts: boolean; counterparty: string | null }
export type QEvent = { id: number; type: string; payload: any; created_at: string }

export type DemoInfo = {
  customer_id: string; drop_card: string; family_card: string; scam_phone: string
  phishing_domain: string; guardian_link_code: string
}

export const CHANNEL_LABEL: Record<string, string> = {
  cellular: 'сотовая связь', whatsapp: 'WhatsApp', telegram: 'Telegram', voip: 'VoIP', unknown: 'звонок',
}
