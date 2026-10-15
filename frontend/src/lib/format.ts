/**
 * Number / money / date formatting for the A-share UI, plus the colour
 * convention of the Chinese market: RED is up / gain / buy, GREEN is
 * down / loss / sell (in both UI languages).
 *
 * Digits are locale-neutral; only large-number units and relative-time words
 * follow the UI language (Chinese myriad units in zh, K/M/B in en).
 */

import { getLang, translate } from '@/i18n/store'

const DASH = '—'

function isNum(n: number | null | undefined): n is number {
  return typeof n === 'number' && Number.isFinite(n)
}

const nfCache = new Map<string, Intl.NumberFormat>()
function nf(min: number, max: number): Intl.NumberFormat {
  const key = `${min}:${max}`
  let f = nfCache.get(key)
  if (!f) {
    f = new Intl.NumberFormat('en-US', { minimumFractionDigits: min, maximumFractionDigits: max })
    nfCache.set(key, f)
  }
  return f
}

/** 1234567.8 -> "1,234,567.80" */
export function fmtNumber(n: number | null | undefined, digits = 2): string {
  return isNum(n) ? nf(digits, digits).format(n) : DASH
}

/** 1234567.8 -> "¥1,234,567.80" */
export function fmtCNY(n: number | null | undefined, digits = 2): string {
  if (!isNum(n)) return DASH
  const sign = n < 0 ? '-' : ''
  return `${sign}¥${nf(digits, digits).format(Math.abs(n))}`
}

/** Signed money: 1234 -> "+¥1,234.00", -5 -> "-¥5.00" */
export function fmtSignedCNY(n: number | null | undefined, digits = 2): string {
  if (!isNum(n)) return DASH
  return `${n > 0 ? '+' : ''}${fmtCNY(n, digits)}`
}

// Units are matched largest first. zh uses the myriad units 10^12, 10^8 and 10^4.
const UNITS: Record<'zh' | 'en', ReadonlyArray<[number, string]>> = {
  zh: [
    [1e12, '万亿'],
    [1e8, '亿'],
    [1e4, '万'],
  ],
  en: [
    [1e12, 'T'],
    [1e9, 'B'],
    [1e6, 'M'],
    [1e3, 'K'],
  ],
}

/** Large numbers in the UI language's units: 123456789 -> "1.23" + 10^8 unit (zh) or "123.46M" (en). */
export function fmtCompact(n: number | null | undefined, digits = 2): string {
  if (!isNum(n)) return DASH
  const abs = Math.abs(n)
  const sign = n < 0 ? '-' : ''
  for (const [size, unit] of UNITS[getLang()]) {
    if (abs >= size) return `${sign}${nf(0, digits).format(abs / size)}${unit}`
  }
  return `${sign}${nf(0, digits).format(abs)}`
}

/** fmtCompact with a yuan sign, e.g. "¥123.46M". */
export function fmtCNYCompact(n: number | null | undefined, digits = 2): string {
  if (!isNum(n)) return DASH
  return `${n < 0 ? '-' : ''}¥${fmtCompact(Math.abs(n), digits)}`
}

/**
 * Format a FRACTION as a percentage: 0.0523 -> "5.23%".
 * With `sign`, positives get a leading "+" (for changes / P&L).
 */
export function fmtPct(ratio: number | null | undefined, opts: { digits?: number; sign?: boolean } = {}): string {
  if (!isNum(ratio)) return DASH
  const { digits = 2, sign = false } = opts
  const pct = ratio * 100
  const body = `${nf(digits, digits).format(pct)}%`
  return sign && pct > 0 ? `+${body}` : body
}

/** Price with 2 decimals (the A-share tick is 0.01). */
export function fmtPrice(n: number | null | undefined, digits = 2): string {
  return fmtNumber(n, digits)
}

/** Shares: 1200 -> "1,200" */
export function fmtShares(n: number | null | undefined): string {
  return isNum(n) ? nf(0, 0).format(n) : DASH
}

/** Generic score: 0.83215 -> "0.8322" */
export function fmtScore(n: number | null | undefined, digits = 4): string {
  return isNum(n) ? n.toFixed(digits) : DASH
}

// ---------------------------------------------------------------------------
// A-share colour helpers
// ---------------------------------------------------------------------------

export type Direction = 'up' | 'down' | 'flat'

export function direction(n: number | null | undefined, epsilon = 1e-9): Direction {
  if (!isNum(n) || Math.abs(n) < epsilon) return 'flat'
  return n > 0 ? 'up' : 'down'
}

/** Tailwind text colour for a change: red up, green down. */
export function changeClass(n: number | null | undefined): string {
  const d = direction(n)
  return d === 'up' ? 'text-up' : d === 'down' ? 'text-down' : 'text-muted'
}

/** buy -> red, sell -> green */
export function sideClass(side: string): string {
  const s = side.toLowerCase()
  return s === 'buy' ? 'text-up' : s === 'sell' ? 'text-down' : 'text-muted'
}

// ---------------------------------------------------------------------------
// Dates
// ---------------------------------------------------------------------------

function parseDate(iso: string | null | undefined): Date | null {
  if (!iso) return null
  // A bare date ("2025-01-02") parses as UTC; keep it as a local calendar day instead.
  const d = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? new Date(`${iso}T00:00:00`) : new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d
}

const pad = (n: number) => String(n).padStart(2, '0')

/** "2025-01-02" */
export function fmtDate(iso: string | null | undefined): string {
  if (iso && /^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso
  const d = parseDate(iso)
  return d ? `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` : DASH
}

/** "2025-01-02 15:04" (or "01-02 15:04" when `short`) in local time. */
export function fmtDateTime(iso: string | null | undefined, short = false): string {
  const d = parseDate(iso)
  if (!d) return DASH
  const time = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  const md = `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  return short ? `${md} ${time}` : `${d.getFullYear()}-${md} ${time}`
}

/** "just now" / "3 min ago" / "2 h ago" / date, in the UI language. */
export function fmtRelative(iso: string | null | undefined, now = Date.now()): string {
  const d = parseDate(iso)
  if (!d) return DASH
  const sec = Math.round((now - d.getTime()) / 1000)
  if (sec < 45) return translate('time.justNow')
  if (sec < 3600) return translate('time.minutesAgo', { n: Math.round(sec / 60) })
  if (sec < 86400) return translate('time.hoursAgo', { n: Math.round(sec / 3600) })
  if (sec < 86400 * 7) return translate('time.daysAgo', { n: Math.round(sec / 86400) })
  return fmtDateTime(iso, true)
}

/** Elapsed time between two ISO instants, e.g. "1m 23s". */
export function fmtDuration(fromIso: string | null | undefined, toIso: string | null | undefined): string {
  const a = parseDate(fromIso)
  const b = parseDate(toIso)
  if (!a || !b) return DASH
  const s = Math.max(0, Math.round((b.getTime() - a.getTime()) / 1000))
  if (s < 60) return translate('duration.s', { s })
  const m = Math.floor(s / 60)
  if (m < 60) return translate('duration.ms', { m, s: s % 60 })
  return translate('duration.hm', { h: Math.floor(m / 60), m: m % 60 })
}

/** Local calendar date as "YYYY-MM-DD". */
export function toISODate(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export function addDays(iso: string, days: number): string {
  const d = parseDate(iso) ?? new Date()
  d.setDate(d.getDate() + days)
  return toISODate(d)
}
