import type { AnalystKey, LLMProvider, Rating, ReportKey, RunStatus, SearchMode } from '@/api/types'

// Domain constants only; every user-visible label lives in src/i18n.

/** Agent graph node names, exactly as the backend emits them in `node` events. */
export const NODE_NAMES = [
  'Market Analyst',
  'Sentiment Analyst',
  'News Analyst',
  'Fundamentals Analyst',
  'Bull Researcher',
  'Bear Researcher',
  'Research Manager',
  'Trader',
  'Aggressive Analyst',
  'Conservative Analyst',
  'Neutral Analyst',
  'Portfolio Manager',
  'Risk Gate',
  'Human Approval',
  'Execute',
  'Record',
] as const
export type NodeName = (typeof NODE_NAMES)[number]

export type PhaseId = 'analysts' | 'investment' | 'trader' | 'risk' | 'pm' | 'gate' | 'approval' | 'execution'

export interface PipelinePhase {
  id: PhaseId
  nodes: readonly NodeName[]
}

export const PIPELINE: readonly PipelinePhase[] = [
  { id: 'analysts', nodes: ['Market Analyst', 'Sentiment Analyst', 'News Analyst', 'Fundamentals Analyst'] },
  { id: 'investment', nodes: ['Bull Researcher', 'Bear Researcher', 'Research Manager'] },
  { id: 'trader', nodes: ['Trader'] },
  { id: 'risk', nodes: ['Aggressive Analyst', 'Conservative Analyst', 'Neutral Analyst'] },
  { id: 'pm', nodes: ['Portfolio Manager'] },
  { id: 'gate', nodes: ['Risk Gate'] },
  { id: 'approval', nodes: ['Human Approval'] },
  { id: 'execution', nodes: ['Execute', 'Record'] },
]

/** Analyst choices on the run form, in display order. */
export const ANALYST_KEYS: readonly AnalystKey[] = ['market', 'sentiment', 'news', 'fundamentals']

/** run.analysts may hold API names or the core's keys (cn_capital / social). */
export const ANALYST_NODE: Record<string, NodeName> = {
  market: 'Market Analyst',
  sentiment: 'Sentiment Analyst',
  cn_capital: 'Sentiment Analyst',
  social: 'Sentiment Analyst',
  news: 'News Analyst',
  fundamentals: 'Fundamentals Analyst',
}

export const REPORTS: ReadonlyArray<{ key: ReportKey; analyst: AnalystKey; node: NodeName }> = [
  { key: 'market_report', analyst: 'market', node: 'Market Analyst' },
  { key: 'sentiment_report', analyst: 'sentiment', node: 'Sentiment Analyst' },
  { key: 'news_report', analyst: 'news', node: 'News Analyst' },
  { key: 'fundamentals_report', analyst: 'fundamentals', node: 'Fundamentals Analyst' },
]

export type Tone = 'up' | 'down' | 'flat' | 'warn' | 'info' | 'accent' | 'muted'

/** A-share colours: bullish ratings red, bearish green. */
export const RATING_TONE: Record<Rating, Tone> = {
  Buy: 'up',
  Overweight: 'up',
  Hold: 'flat',
  Underweight: 'down',
  Sell: 'down',
  REVIEW: 'warn',
}

const RATINGS = Object.keys(RATING_TONE) as Rating[]

/** Case-insensitive match of a free-form rating string to a known Rating. */
export function normalizeRating(rating: string | null | undefined): Rating | null {
  if (!rating) return null
  return RATINGS.find((r) => r.toLowerCase() === rating.toLowerCase()) ?? null
}

export const STATUS_TONE: Record<RunStatus, Tone> = {
  queued: 'muted',
  running: 'accent',
  awaiting_approval: 'warn',
  completed: 'info',
  rejected: 'flat',
  failed: 'up',
}

export const SEARCH_MODES: readonly SearchMode[] = ['vector', 'keyword', 'hybrid', 'hybrid_rerank']

/** Shares per board lot; buys must be a multiple of this. */
export const LOT_SIZE = 100

/** Short brand names for badges (proper nouns, same in every UI language). */
export const PROVIDER_SHORT: Record<LLMProvider, string> = {
  deepseek: 'DeepSeek',
  openai: 'OpenAI',
  anthropic: 'Claude',
}

export function providerShort(provider: string | null | undefined): string {
  if (!provider) return ''
  return (PROVIDER_SHORT as Record<string, string>)[provider] ?? provider
}
