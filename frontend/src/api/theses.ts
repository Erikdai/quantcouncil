import { request } from './client'
import type { ResearchCitation, ResearchEvidence } from './deepResearch'

export interface Rule {
  template: 'trend' | 'threshold' | 'relative' | 'coverage'
  period: 'annual' | 'latest_reported'
  metric: string; operator: 'gt' | 'gte' | 'lt' | 'lte'; threshold: string | null
  coverage_expectation: 'covers' | 'shortfall'; observations: number; target_segment: string | null; cash_outflows: string[]
}
export interface Candidate {
  origin_path: string; original_text: string; statement: string
  verification_class: string; relationship: string; rule: Rule | null
  suggested_assumptions: string[]; limitations: string[]; extraction_errors: string[]; citations: ResearchCitation[]
}
export interface Extraction { id: string; source_job_id: string; status: string; candidates: Candidate[]; error: string | null }
export interface ThesisVersion {
  id: string; number: number; statement: string; horizon: 'until_paused'; rule: Rule | null; contract_hash: string
  origin: Candidate & { source_job_id: string; source_cutoff: string; source_checks_passed: boolean }
  meaning_review: { rule_matches_statement: boolean; relationship: string; issues: string[]; assumptions: string[]; explanation: string } | null
  baseline_review_id: string | null; confirmed_at: string | null
}
export interface ThesisReview {
  id: string; version_id: string; kind: string; status: string; as_of: string; created_at: string; unread: boolean; error: string | null
  result: { judgment: string; eligible: boolean; reason: string; checks: Record<string, unknown>[]; eligibility_errors?: string[]; sources: ResearchEvidence[]; scope_review?: { explanation: string; issues: string[] } } | null
  snapshot: { fetched_at: string; manifest: { form: string; filed: string; period: string; url: string }[] } | null
}
export interface ThesisSummary { id: string; ticker: string; lifecycle: string; current_version: number; judgment: string | null; data_health: string; statement: string; last_checked_at: string | null; next_check_at: string | null }
export interface Thesis extends ThesisSummary { versions: ThesisVersion[]; reviews: ThesisReview[] }
interface VersionInput { statement: string; rule: Rule | null; horizon: 'until_paused' }
export const busy = (s?: string) => s === 'queued' || s === 'running'
export const theses = {
  list: () => request<ThesisSummary[]>('/theses'),
  get: (id: string) => request<Thesis>(`/theses/${id}`),
  extract: (source_job_id: string) => request<Extraction>('/theses/extractions', { method: 'POST', body: { source_job_id } }),
  extraction: (id: string) => request<Extraction>(`/theses/extractions/${id}`),
  create: (body: VersionInput & { extraction_id: string; candidate_index: number }) => request<{ thesis_id: string }>('/theses', { method: 'POST', body }),
  revise: (id: string, body: VersionInput) => request('/theses/' + id + '/versions', { method: 'POST', body }),
  confirm: (id: string, body: { version_id: string; contract_hash: string; acknowledge_baseline: true; accept_reformulation: boolean; start_monitoring: boolean }) => request('/theses/' + id + '/confirm', { method: 'POST', body }),
  check: (id: string, as_of: string | null) => request('/theses/' + id + '/checks', { method: 'POST', body: { as_of } }),
  lifecycle: (id: string, lifecycle: string) => request('/theses/' + id + '/lifecycle', { method: 'PATCH', body: { lifecycle } }),
  read: (id: string, review: string) => request(`/theses/${id}/reviews/${review}/read`, { method: 'POST' }),
}
