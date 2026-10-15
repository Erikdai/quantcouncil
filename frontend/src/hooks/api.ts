import { useCallback } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import {
  TERMINAL_STATUSES,
  type ApprovalRequest,
  type IngestRequest,
  type KlineOut,
  type LLMSettingsIn,
  type RunCreate,
  type RunOut,
  type RunStatus,
  type SearchMode,
} from '@/api/types'
import { addDays } from '@/lib/format'

export const qk = {
  health: ['health'] as const,
  runs: (status: RunStatus | null, limit: number) => ['runs', { status, limit }] as const,
  runsAll: ['runs'] as const,
  run: (id: string) => ['run', id] as const,
  portfolio: (account: string) => ['portfolio', account] as const,
  orders: (limit: number) => ['orders', limit] as const,
  kline: (ticker: string, start: string, end: string) => ['kline', ticker, start, end] as const,
  watchlist: ['watchlist'] as const,
  documents: (ticker: string | null) => ['documents', ticker] as const,
  search: (q: string, ticker: string | null, mode: SearchMode, k: number) => ['search', { q, ticker, mode, k }] as const,
  skills: ['skills'] as const,
  skill: (name: string) => ['skill', name] as const,
  llmCatalog: ['llm', 'catalog'] as const,
  llmSettings: ['llm', 'settings'] as const,
}

export const isTerminal = (status: RunStatus | null | undefined) => !!status && TERMINAL_STATUSES.has(status)

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export function useHealth() {
  return useQuery({
    queryKey: qk.health,
    queryFn: ({ signal }) => api.health(signal),
    refetchInterval: 30_000,
    retry: false,
  })
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

export function useRuns(status: RunStatus | null = null, limit = 50) {
  return useQuery({
    queryKey: qk.runs(status, limit),
    queryFn: ({ signal }) => api.listRuns({ status, limit }, signal),
    placeholderData: keepPreviousData,
    // Poll while anything is still in flight.
    refetchInterval: (q) => (q.state.data?.some((r) => !isTerminal(r.status)) ? 5_000 : false),
  })
}

export function useRun(id: string | undefined) {
  return useQuery({
    queryKey: qk.run(id ?? ''),
    queryFn: ({ signal }) => api.getRun(id ?? '', signal),
    enabled: !!id,
    // SSE drives freshness; a slow poll is the safety net for missed events.
    refetchInterval: (q) => (q.state.data && !isTerminal(q.state.data.status) ? 15_000 : false),
  })
}

export function useCreateRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: RunCreate) => api.createRun(body),
    meta: { errorTitle: 'err.createRun' },
    onSuccess: (run) => {
      qc.setQueryData(qk.run(run.id), run)
      void qc.invalidateQueries({ queryKey: qk.runsAll })
    },
  })
}

export function useApproveRun(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ApprovalRequest) => api.approveRun(id, body),
    meta: { errorTitle: 'err.approve' },
    onSuccess: (run) => {
      qc.setQueryData(qk.run(id), run)
      void qc.invalidateQueries({ queryKey: qk.runsAll })
    },
  })
}

export function useEvaluateRun(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.evaluateRun(id),
    meta: { errorTitle: 'err.evaluate' },
    onSuccess: (result) => {
      qc.setQueryData<RunOut>(qk.run(id), (prev) =>
        prev ? { ...prev, evals: [...prev.evals.filter((e) => e.id !== result.id), result] } : prev,
      )
    },
  })
}

// ---------------------------------------------------------------------------
// Portfolio
// ---------------------------------------------------------------------------

export function usePortfolio(account = 'default') {
  return useQuery({
    queryKey: qk.portfolio(account),
    queryFn: ({ signal }) => api.portfolio(account, signal),
    refetchInterval: 30_000,
  })
}

export function useOrders(limit = 50) {
  return useQuery({
    queryKey: qk.orders(limit),
    queryFn: ({ signal }) => api.orders(limit, signal),
    refetchInterval: 30_000,
  })
}

export function useResetPortfolio() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (initialCash: number) => api.resetPortfolio(initialCash),
    meta: { errorTitle: 'err.reset' },
    onSuccess: (pf) => {
      qc.setQueryData(qk.portfolio(pf.account.id), pf)
      void qc.invalidateQueries({ queryKey: ['orders'] })
    },
  })
}

// ---------------------------------------------------------------------------
// Market data
// ---------------------------------------------------------------------------

/** ~120 trading bars ending at `tradeDate` (180 calendar days covers holidays). */
export function useKline(ticker: string | undefined, tradeDate: string | undefined) {
  const end = tradeDate ?? ''
  const start = tradeDate ? addDays(tradeDate, -185) : ''
  // Stable selector: the run page re-renders on every SSE frame and the chart must not reset.
  const select = useCallback(
    (data: KlineOut): KlineOut => ({
      ...data,
      bars: (data.bars ?? []).filter((b) => b.time <= end).slice(-120),
    }),
    [end],
  )
  return useQuery({
    queryKey: qk.kline(ticker ?? '', start, end),
    queryFn: ({ signal }) => api.kline(ticker ?? '', start, end, signal),
    enabled: !!ticker && !!tradeDate,
    staleTime: 5 * 60_000,
    select,
  })
}

// ---------------------------------------------------------------------------
// Watchlist
// ---------------------------------------------------------------------------

export function useWatchlist() {
  return useQuery({ queryKey: qk.watchlist, queryFn: ({ signal }) => api.watchlist(signal) })
}

export function useAddWatch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ticker: string) => api.addWatch(ticker),
    meta: { errorTitle: 'err.addWatch' },
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.watchlist }),
  })
}

export function useRemoveWatch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ticker: string) => api.removeWatch(ticker),
    meta: { errorTitle: 'err.removeWatch' },
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.watchlist }),
  })
}

// ---------------------------------------------------------------------------
// Research
// ---------------------------------------------------------------------------

export function useDocuments(ticker: string | null, poll = false) {
  return useQuery({
    queryKey: qk.documents(ticker),
    queryFn: ({ signal }) => api.documents(ticker, signal),
    placeholderData: keepPreviousData,
    // After an ingest, poll for a while: documents appear asynchronously.
    refetchInterval: poll ? 4_000 : false,
  })
}

export function useIngest() {
  return useMutation({
    mutationFn: (body: IngestRequest) => api.ingest(body),
    meta: { errorTitle: 'err.ingest' },
  })
}

export function useSearch(q: string, ticker: string | null, mode: SearchMode, k = 8) {
  return useQuery({
    queryKey: qk.search(q, ticker, mode, k),
    queryFn: ({ signal }) => api.search({ q, ticker, mode, k }, signal),
    enabled: q.trim().length > 0,
    staleTime: 60_000,
  })
}

// ---------------------------------------------------------------------------
// Skills
// ---------------------------------------------------------------------------

export function useSkills() {
  return useQuery({ queryKey: qk.skills, queryFn: ({ signal }) => api.skills(signal), staleTime: 5 * 60_000 })
}

export function useSkill(name: string | undefined) {
  return useQuery({
    queryKey: qk.skill(name ?? ''),
    queryFn: ({ signal }) => api.skill(name ?? '', signal),
    enabled: !!name,
    staleTime: 5 * 60_000,
  })
}

// ---------------------------------------------------------------------------
// LLM settings
// ---------------------------------------------------------------------------

export function useLlmCatalog() {
  return useQuery({ queryKey: qk.llmCatalog, queryFn: ({ signal }) => api.llmCatalog(signal), staleTime: 10 * 60_000 })
}

export function useLlmSettings() {
  return useQuery({ queryKey: qk.llmSettings, queryFn: ({ signal }) => api.llmSettings(signal), staleTime: 60_000 })
}

export function useSaveLlmSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: LLMSettingsIn) => api.saveLlmSettings(body),
    meta: { errorTitle: 'err.saveSettings' },
    onSuccess: (saved) => qc.setQueryData(qk.llmSettings, saved),
  })
}

/** Provider errors come back as `{ok: false, error}`; only transport failures reach onError. */
export function useTestLlm() {
  return useMutation({
    mutationFn: (body: LLMSettingsIn) => api.testLlm(body),
    meta: { errorTitle: 'err.testLlm' },
  })
}
