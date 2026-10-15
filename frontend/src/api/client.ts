import type {
  ExportFormat,
  ExportLang,
  HoldingIn,
  ApprovalRequest,
  DocumentOut,
  ErrorBody,
  EvalResultOut,
  HealthOut,
  IngestOut,
  IngestRequest,
  KlineOut,
  LLMSettingsIn,
  LLMSettingsOut,
  LLMTestResult,
  ProviderInfo,
  OrderOut,
  PortfolioOut,
  RunCreate,
  RunOut,
  RunStatus,
  RunSummary,
  SearchMode,
  SearchOut,
  SkillOut,
  WatchItem,
} from './types'
import { translate, translateDynamic } from '@/i18n/store'

export const API_BASE = '/api'

/** Any failed API call. `status` is 0 when the server could not be reached. */
export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

type Query = Record<string, string | number | boolean | null | undefined>

export function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams()
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
    }
  }
  const qs = params.toString()
  return `${API_BASE}${path}${qs ? `?${qs}` : ''}`
}

/** Turn FastAPI's `{detail}` (a string, an object or a validation list) into one readable line. */
export function formatDetail(detail: unknown): string | null {
  if (detail == null) return null
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (item && typeof item === 'object') {
        const rec = item as Record<string, unknown>
        const loc = Array.isArray(rec.loc) ? rec.loc.filter((p) => p !== 'body').join('.') : ''
        const msg = typeof rec.msg === 'string' ? rec.msg : JSON.stringify(rec)
        return loc ? `${loc}: ${msg}` : msg
      }
      return String(item)
    })
    return parts.join('; ')
  }
  if (typeof detail === 'object') {
    const rec = detail as Record<string, unknown>
    if (typeof rec.message === 'string') return rec.message
    return JSON.stringify(detail)
  }
  return String(detail)
}

/** Readable fallback for a status code when the body has no `detail`. */
function statusText(status: number): string {
  return translateDynamic(`http.${status}`, `HTTP ${status}`)
}

/** Build an ApiError from a non-2xx response, reading `{detail}` when the body is JSON. */
export async function errorFromResponse(res: Response): Promise<ApiError> {
  let detail: unknown
  try {
    const text = await res.text()
    if (text) {
      try {
        detail = (JSON.parse(text) as ErrorBody).detail ?? text
      } catch {
        detail = text.length > 300 ? `${text.slice(0, 300)}…` : text
      }
    }
  } catch {
    // body unreadable: fall back to the status line
  }
  const message = formatDetail(detail) ?? statusText(res.status)
  return new ApiError(res.status, message, detail)
}

/** fetch() that maps network failures to ApiError(status 0). */
export async function rawFetch(url: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init)
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(0, translate('http.network'), err)
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  query?: Query
  body?: unknown
  signal?: AbortSignal
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = 'GET', query, body, signal } = opts
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const res = await rawFetch(buildUrl(path, query), {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })
  if (!res.ok) throw await errorFromResponse(res)
  if (res.status === 204) return undefined as T

  const text = await res.text()
  if (!text) return undefined as T
  try {
    return JSON.parse(text) as T // JSON boundary: trusted to match the contract
  } catch {
    throw new ApiError(res.status, translate('http.badJson'), text.slice(0, 300))
  }
}

/** File name from Content-Disposition, preferring the RFC 5987 `filename*=UTF-8''…` form. */
export function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null
  const star = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(header)
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1].trim())
    } catch {
      // malformed escape: fall back to the plain filename
    }
  }
  return /filename\s*=\s*"?([^";]+)"?/i.exec(header)?.[1]?.trim() ?? null
}

/** GET a file and save it via a temporary object URL; resolves with the file name. */
export async function downloadFile(path: string, query?: Query): Promise<string> {
  const res = await rawFetch(buildUrl(path, query))
  if (!res.ok) throw await errorFromResponse(res)
  const blob = await res.blob()
  const name = filenameFromDisposition(res.headers.get('Content-Disposition')) ?? 'report'
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  // Revoke later: some browsers read the URL asynchronously after click().
  setTimeout(() => URL.revokeObjectURL(url), 30_000)
  return name
}

export function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message
  return typeof err === 'string' ? err : translate('error.unknown')
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

const enc = encodeURIComponent

export const api = {
  health: (signal?: AbortSignal) => request<HealthOut>('/health', { signal }),

  // runs
  createRun: (body: RunCreate) => request<RunOut>('/runs', { method: 'POST', body }),
  listRuns: (params: { limit?: number; status?: RunStatus | null } = {}, signal?: AbortSignal) =>
    request<RunSummary[]>('/runs', { query: { limit: params.limit ?? 50, status: params.status }, signal }),
  getRun: (id: string, signal?: AbortSignal) => request<RunOut>(`/runs/${enc(id)}`, { signal }),
  approveRun: (id: string, body: ApprovalRequest) =>
    request<RunOut>(`/runs/${enc(id)}/approval`, { method: 'POST', body }),
  evaluateRun: (id: string) => request<EvalResultOut>(`/runs/${enc(id)}/evaluate`, { method: 'POST' }),
  runEventsUrl: (id: string) => buildUrl(`/runs/${enc(id)}/events`),

  // portfolio
  portfolio: (accountId = 'default', signal?: AbortSignal) =>
    request<PortfolioOut>('/portfolio', { query: { account_id: accountId }, signal }),
  orders: (limit = 50, signal?: AbortSignal) =>
    request<OrderOut[]>('/portfolio/orders', { query: { limit }, signal }),
  resetPortfolio: (initialCash: number) =>
    request<PortfolioOut>('/portfolio/reset', { method: 'POST', body: { initial_cash: initialCash } }),
  /** Enter or edit a holding the user already owns (no cash moves; quantity 0 removes it). */
  setHolding: (ticker: string, body: HoldingIn, accountId = 'default') =>
    request<PortfolioOut>(`/portfolio/positions/${enc(ticker)}`, {
      method: 'PUT',
      body,
      query: { account_id: accountId },
    }),
  removeHolding: (ticker: string, accountId = 'default') =>
    request<PortfolioOut>(`/portfolio/positions/${enc(ticker)}`, {
      method: 'DELETE',
      query: { account_id: accountId },
    }),
  setCash: (cash: number, accountId = 'default') =>
    request<PortfolioOut>('/portfolio/cash', { method: 'PUT', body: { cash }, query: { account_id: accountId } }),

  // exports (files)
  exportDaily: (params: { format: ExportFormat; lang: ExportLang; day?: string | null; accountId?: string }) =>
    downloadFile('/reports/daily', {
      format: params.format,
      lang: params.lang,
      day: params.day,
      account_id: params.accountId ?? 'default',
    }),
  exportRun: (id: string, params: { format: ExportFormat; lang: ExportLang }) =>
    downloadFile(`/runs/${enc(id)}/report`, { format: params.format, lang: params.lang }),

  // market data
  kline: (ticker: string, start: string, end: string, signal?: AbortSignal) =>
    request<KlineOut>(`/market/kline/${enc(ticker)}`, { query: { start, end }, signal }),

  // watchlist
  watchlist: (signal?: AbortSignal) => request<WatchItem[]>('/watchlist', { signal }),
  addWatch: (ticker: string) => request<WatchItem>('/watchlist', { method: 'POST', body: { ticker } }),
  removeWatch: (ticker: string) => request<void>(`/watchlist/${enc(ticker)}`, { method: 'DELETE' }),

  // research
  search: (
    params: { q: string; ticker?: string | null; k?: number; mode?: SearchMode },
    signal?: AbortSignal,
  ) =>
    request<SearchOut>('/research/search', {
      query: { q: params.q, ticker: params.ticker, k: params.k ?? 8, mode: params.mode ?? 'hybrid' },
      signal,
    }),
  ingest: (body: IngestRequest) => request<IngestOut>('/research/ingest', { method: 'POST', body }),
  documents: (ticker?: string | null, signal?: AbortSignal) =>
    request<DocumentOut[]>('/research/documents', { query: { ticker }, signal }),
  chatUrl: () => buildUrl('/research/chat'),

  // skills
  skills: (signal?: AbortSignal) => request<SkillOut[]>('/skills', { signal }),
  skill: (name: string, signal?: AbortSignal) => request<SkillOut>(`/skills/${enc(name)}`, { signal }),

  // LLM settings
  llmCatalog: (signal?: AbortSignal) => request<ProviderInfo[]>('/settings/llm/catalog', { signal }),
  llmSettings: (signal?: AbortSignal) => request<LLMSettingsOut>('/settings/llm', { signal }),
  saveLlmSettings: (body: LLMSettingsIn) => request<LLMSettingsOut>('/settings/llm', { method: 'PUT', body }),
  /** Sends one short prompt with the given (unsaved) settings; can take ~30 s. */
  testLlm: (body: LLMSettingsIn) => request<LLMTestResult>('/settings/llm/test', { method: 'POST', body }),
}
