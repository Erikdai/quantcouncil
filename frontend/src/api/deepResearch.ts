import { request } from './client'

export interface ResearchCitation { source_id: string; quote: string }
export interface ResearchFinding { text: string; kind: 'fact' | 'inference'; citations: ResearchCitation[] }
export interface ResearchEvidence {
  id: string; kind: 'filing' | 'financial' | 'calculation'; title: string; url: string
  filed: string; content: string; sha256: string | null; inputs: string[]
  data: Record<string, unknown>
}
export interface ResearchReport {
  title: string; verdict: 'supported' | 'mixed' | 'not_supported' | 'insufficient'
  answer: ResearchFinding; findings: ResearchFinding[]; counterarguments: ResearchFinding[]
  unknowns: string[]; what_would_change: string[]
}
export interface ResearchSummary {
  id: string; ticker: string; question: string; as_of: string; language: 'zh' | 'en'
  status: string; stage: string; created_at: string; updated_at: string; error: string | null
}
export interface ResearchJob extends ResearchSummary {
  plan: { subquestions: string[]; search_queries: string[]; metrics: string[] } | null
  report: ResearchReport | null; sources: ResearchEvidence[]
  events: { at: string; stage: string; message: string }[]
  model: { provider: string; deep_model: string }
  verification: { passed: boolean; citations_checked: number; errors: string[]; semantic_review?: { passed: boolean; scope: string } | null } | null
  manifest: { form: string; period: string; filed: string; url: string; sha256: string }[]
  warnings: string[]
}
export const researchActive = (status?: string) => status === 'queued' || status === 'running'
export const deepResearch = {
  list: (signal?: AbortSignal) => request<ResearchSummary[]>('/deep-research', { signal }),
  get: (id: string, signal?: AbortSignal) => request<ResearchJob>(`/deep-research/${id}`, { signal }),
  create: (body: { ticker: string; question: string; as_of: string | null; language: 'zh' | 'en' }) =>
    request<ResearchJob>('/deep-research', { method: 'POST', body }),
  cancel: (id: string) => request<ResearchJob>(`/deep-research/${id}/cancel`, { method: 'POST' }),
  retry: (id: string) => request<ResearchJob>(`/deep-research/${id}/retry`, { method: 'POST' }),
}
