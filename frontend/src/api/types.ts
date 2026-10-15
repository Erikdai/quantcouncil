/**
 * TypeScript mirror of quantcouncil/api/schemas.py (the backend's HTTP contract).
 *
 * Conventions: Python `date` / `datetime` arrive as ISO strings; `X | None`
 * fields are `X | null`; fields with a Pydantic default are optional on input
 * models but always present on output models.
 */

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

export const RUN_STATUSES = [
  'queued',
  'running',
  'awaiting_approval',
  'completed',
  'rejected',
  'failed',
] as const
export type RunStatus = (typeof RUN_STATUSES)[number]

export const TERMINAL_STATUSES: ReadonlySet<RunStatus> = new Set<RunStatus>(['completed', 'rejected', 'failed'])

export const RUN_EVENT_TYPES = [
  'status',
  'node',
  'token',
  'tool_call',
  'tool_result',
  'report',
  'debate',
  'plan',
  'decision',
  'risk_check',
  'approval_required',
  'approval',
  'execution',
  'memory',
  'done',
  'error',
] as const
export type RunEventType = (typeof RUN_EVENT_TYPES)[number]

/** Portfolio Manager ratings; REVIEW means the run needs a human look. */
export type Rating = 'Buy' | 'Overweight' | 'Hold' | 'Underweight' | 'Sell' | 'REVIEW'

/** Analyst keys accepted by RunCreate.analysts. */
export type AnalystKey = 'market' | 'sentiment' | 'news' | 'fundamentals'

export type ReportKey = 'market_report' | 'sentiment_report' | 'news_report' | 'fundamentals_report'

export type OrderSide = 'buy' | 'sell'

export type ApprovalAction = 'approve' | 'reject' | 'modify'

export type SearchMode = 'vector' | 'keyword' | 'hybrid' | 'hybrid_rerank'

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

export interface RunCreate {
  /** A-share code in any form (600519, 600519.SH, sz000001) or a US ticker. */
  ticker: string
  /** YYYY-MM-DD; null = latest trading day. */
  trade_date?: string | null
  analysts?: AnalystKey[] | null
  auto_approve?: boolean
  account_id?: string
  max_debate_rounds?: number | null
}

export interface RiskViolation {
  rule: string
  message: string
  severity: 'block' | 'warn'
}

export interface OrderProposal {
  ticker: string
  side: OrderSide
  /** Shares, a multiple of the 100-share lot for buys. */
  quantity: number
  /** Reference fill price (CNY). */
  price: number
  notional: number
  est_fees: number
  target_weight: number
  current_weight: number
}

export interface RiskCheck {
  rating: string
  /** True when an order exists and no blocking rule fired. */
  approved: boolean
  order: OrderProposal | null
  violations: RiskViolation[]
  warnings: RiskViolation[]
  /** Prices and limits the check used (limit_up, limit_down, prev_close, ...). */
  reference: Record<string, unknown>
}

export interface ApprovalRequest {
  action: ApprovalAction
  quantity?: number | null
  comment?: string | null
}

export interface Execution {
  order_id: string
  ticker: string
  side: OrderSide
  quantity: number
  price: number
  fees: Record<string, number>
  cash_after: number
  status: 'filled' | 'rejected'
  reason: string | null
}

export interface RunSummary {
  id: string
  ticker: string
  name: string | null
  market: string
  trade_date: string
  status: RunStatus
  rating: string | null
  created_at: string
  finished_at: string | null
}

export interface EvalResultOut {
  id: number
  run_id: string
  evaluator: string
  scores: Record<string, number>
  passed: boolean
  comment: string | null
  created_at: string
}

export interface RunOut extends RunSummary {
  analysts: string[]
  auto_approve: boolean
  /** market_report, sentiment_report, news_report, fundamentals_report */
  reports: Record<string, string>
  investment_debate: string | null
  risk_debate: string | null
  investment_plan: string | null
  trader_plan: string | null
  final_decision: string | null
  risk_check: RiskCheck | null
  approval: Record<string, unknown> | null
  execution: Execution | null
  error: string | null
  trace_url: string | null
  evals: EvalResultOut[]
  /** LLM settings snapshot the run used (no keys); absent on runs before the settings feature. */
  llm?: Partial<LLMSettings> | null
}

// ---------------------------------------------------------------------------
// Portfolio
// ---------------------------------------------------------------------------

export interface AccountOut {
  id: string
  cash: number
  initial_cash: number
  market_value: number
  equity: number
  pnl: number
  /** Fraction, e.g. 0.052 = +5.2%. */
  pnl_pct: number
  peak_equity: number
  /** Fraction of peak equity, e.g. 0.031 = 3.1% below peak. */
  drawdown_pct: number
}

export interface PositionOut {
  ticker: string
  name: string | null
  quantity: number
  /** Sellable today (T+1: shares bought today are not). */
  available_quantity: number
  avg_cost: number
  last_price: number | null
  market_value: number | null
  unrealized_pnl: number | null
  /** Fraction of equity. */
  weight: number | null
}

export interface PortfolioOut {
  account: AccountOut
  positions: PositionOut[]
  /** Hash chain of the ledger re-verified on read. */
  ledger_verified: boolean
}

export interface OrderOut {
  id: string
  run_id: string | null
  ticker: string
  side: string
  quantity: number
  price: number
  fees: number
  status: string
  comment: string | null
  created_at: string
}

export interface ResetRequest {
  initial_cash: number
}

/** A holding the user already owns (PUT /api/portfolio/positions/{ticker}); quantity 0 removes it. */
export interface HoldingIn {
  quantity: number
  avg_cost: number
}

export interface CashIn {
  cash: number
}

// ---------------------------------------------------------------------------
// Exports (GET /api/reports/daily, GET /api/runs/{id}/report)
// ---------------------------------------------------------------------------

export type ExportFormat = 'pdf' | 'docx'
export type ExportLang = 'zh' | 'en'

// ---------------------------------------------------------------------------
// Market data & watchlist
// ---------------------------------------------------------------------------

export interface Bar {
  /** YYYY-MM-DD */
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface KlineOut {
  ticker: string
  name: string | null
  bars: Bar[]
}

export interface WatchItem {
  ticker: string
  name: string | null
  enabled: boolean
  added_at: string | null
}

export interface WatchCreate {
  ticker: string
}

// ---------------------------------------------------------------------------
// Research (RAG + chat)
// ---------------------------------------------------------------------------

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatRequest {
  messages: ChatMessage[]
  ticker?: string | null
  thread_id?: string | null
}

export interface Citation {
  chunk_id: number
  document_id: number
  title: string
  url: string | null
  ticker: string | null
  published_at: string | null
  /** announcement | research | news */
  doc_type: string
  snippet: string
  score: number
}

export interface SearchOut {
  query: string
  mode: string
  results: Citation[]
}

export interface IngestRequest {
  ticker: string
  kinds?: Array<'announcement' | 'research'>
  since?: string | null
  limit?: number
}

export interface IngestOut {
  task_id: string
}

export interface DocumentOut {
  id: number
  ticker: string | null
  title: string
  doc_type: string
  url: string | null
  published_at: string | null
  chunks: number
  created_at: string
}

// ---------------------------------------------------------------------------
// LLM settings (/api/settings, mirrors quantcouncil/llm_settings.py)
// ---------------------------------------------------------------------------

export const LLM_PROVIDERS = ['deepseek', 'openai', 'anthropic'] as const
export type LLMProvider = (typeof LLM_PROVIDERS)[number]

export const OUTPUT_LANGUAGES = ['auto', 'Simplified Chinese', 'English'] as const
export type OutputLanguage = (typeof OUTPUT_LANGUAGES)[number]

export interface ProviderInfo {
  id: LLMProvider
  label: string
  quick_models: string[]
  deep_models: string[]
}

export interface LLMSettings {
  provider: LLMProvider
  quick_model: string
  deep_model: string
  /** Endpoint override (proxy / gateway); null = provider default. */
  base_url: string | null
  /** 0-2; null = provider default. */
  temperature: number | null
  /** 1-5 */
  max_debate_rounds: number
  /** 1-5 */
  max_risk_rounds: number
  output_language: OutputLanguage
}

export interface KeyStatus {
  set: boolean
  source: 'ui' | 'env' | null
  /** Masked key, e.g. "sk-ant...QwAA"; keys themselves are never returned. */
  hint: string | null
}

export interface LLMSettingsOut extends LLMSettings {
  keys: Partial<Record<LLMProvider, KeyStatus>>
}

export interface LLMSettingsIn extends LLMSettings {
  /** New key for the selected provider; omit / null keeps the saved one. */
  api_key?: string | null
  /** Remove the UI-saved key of the selected provider. */
  clear_key?: boolean
}

export interface LLMTestResult {
  ok: boolean
  latency_ms: number | null
  model: string
  reply: string | null
  error: string | null
}

// ---------------------------------------------------------------------------
// Skills, health
// ---------------------------------------------------------------------------

export interface SkillOut {
  name: string
  description: string
  /** SKILL.md body (Markdown); only on GET /api/skills/{name}. */
  body: string | null
}

export interface HealthOut {
  status: 'ok' | 'degraded'
  version: string
  services: Record<string, string>
}

/** Non-2xx error body (FastAPI): a message or a validation error list. */
export interface ErrorBody {
  detail: string | Record<string, unknown> | Array<Record<string, unknown>>
}

// ---------------------------------------------------------------------------
// Run events (SSE: GET /api/runs/{id}/events)
// ---------------------------------------------------------------------------

export interface RunEventPayloads {
  status: { status: RunStatus }
  node: { node: string; phase: 'start' | 'end'; error?: string | null }
  token: { node: string; text: string }
  tool_call: { node: string; tool: string; args: Record<string, unknown> }
  tool_result: { node: string; tool: string; preview: string }
  report: { key: ReportKey; title: string; content: string }
  debate: { stage: 'investment' | 'risk'; speaker: string; content: string }
  plan: { kind: 'investment_plan' | 'trader_plan'; content: string }
  decision: { rating: Rating; content: string }
  risk_check: RiskCheck
  approval_required: { order: OrderProposal; risk_check: RiskCheck }
  approval: { action: ApprovalAction; quantity: number | null; comment: string | null }
  execution: Execution
  memory: { lessons: number; note: string }
  done: { status: RunStatus }
  error: { message: string }
}

/** Discriminated union of every run event (the `data:` JSON of an SSE message). */
export type RunEvent = {
  [K in RunEventType]: { type: K; run_id: string; ts: string; data: RunEventPayloads[K] }
}[RunEventType]

// ---------------------------------------------------------------------------
// Research chat (SSE in the response of POST /api/research/chat)
// ---------------------------------------------------------------------------

export interface ChatEventPayloads {
  token: { text: string }
  tool_call: { tool: string; args: Record<string, unknown> }
  tool_result: { tool: string; preview: string }
  citations: { items: Citation[] }
  done: Record<string, never>
  error: { message: string }
}

export type ChatEventType = keyof ChatEventPayloads

export type ChatEvent = {
  [K in ChatEventType]: { type: K; data: ChatEventPayloads[K] }
}[ChatEventType]
