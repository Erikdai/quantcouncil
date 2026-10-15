import { useMemo } from 'react'
import type { LiveNode, RunLiveState } from '@/api/sse'
import { TERMINAL_STATUSES, type Execution, type OrderProposal, type RiskCheck, type RunOut, type RunStatus } from '@/api/types'
import type { MessageKey } from '@/i18n/store'
import { ANALYST_NODE, PIPELINE, REPORTS, type NodeName, type PhaseId } from '@/lib/constants'
import { parseDebate, type DebateSide, type DebateTurn } from '@/lib/debate'

export type NodeStatus = 'pending' | 'running' | 'done' | 'skipped' | 'waiting'

export interface NodeView {
  name: NodeName
  status: NodeStatus
  live: LiveNode | undefined
  /** Markdown deliverable (live event or persisted run field). */
  final: string | undefined
  /** Message key of a short status note, translated at render time. */
  note?: MessageKey
}

export interface PhaseView {
  id: PhaseId
  nodes: NodeView[]
  status: NodeStatus
}

export interface RunView {
  status: RunStatus
  rating: string | null
  terminal: boolean
  phases: PhaseView[]
  activeNode: NodeName | null
  reports: Partial<Record<string, string>>
  investmentDebate: DebateTurn[]
  riskDebate: DebateTurn[]
  investmentPlan: string | null
  traderPlan: string | null
  decision: string | null
  riskCheck: RiskCheck | null
  /** Order awaiting a human decision (when status is awaiting_approval). */
  pendingOrder: OrderProposal | null
  needsApproval: boolean
  approval: Record<string, unknown> | null
  execution: Execution | null
  errors: string[]
}

function lastTurn(turns: DebateTurn[], side: DebateSide): string | undefined {
  for (let i = turns.length - 1; i >= 0; i--) if (turns[i]?.side === side) return turns[i]?.content
  return undefined
}

function phaseStatus(nodes: NodeView[]): NodeStatus {
  if (nodes.some((n) => n.status === 'running')) return 'running'
  if (nodes.some((n) => n.status === 'waiting')) return 'waiting'
  if (nodes.length > 0 && nodes.every((n) => n.status === 'skipped')) return 'skipped'
  if (nodes.length > 0 && nodes.every((n) => n.status === 'done' || n.status === 'skipped')) return 'done'
  return 'pending'
}

/** Merge the persisted run (source of truth once finished) with the live event stream. */
export function useRunView(run: RunOut | undefined, live: RunLiveState): RunView | null {
  return useMemo(() => {
    if (!run) return null

    // ---- status: a terminal run row wins; otherwise the stream is fresher.
    let status: RunStatus = run.status
    if (!TERMINAL_STATUSES.has(run.status) && live.status) status = live.status
    // An approval we just POSTed resumes the run before the stream says so.
    if (status === 'awaiting_approval' && (run.approval || live.approval) && run.status !== 'awaiting_approval')
      status = run.status
    const terminal = TERMINAL_STATUSES.has(status)

    // ---- deliverables
    const reports: Record<string, string> = { ...run.reports }
    for (const [k, v] of Object.entries(live.reports)) if (v) reports[k] = v.content

    const investmentDebate = live.debates.investment.length ? live.debates.investment : parseDebate(run.investment_debate)
    const riskDebate = live.debates.risk.length ? live.debates.risk : parseDebate(run.risk_debate)
    const investmentPlan = live.plans.investment_plan ?? run.investment_plan
    const traderPlan = live.plans.trader_plan ?? run.trader_plan
    const decision = live.decision?.content ?? run.final_decision
    const rating = live.decision?.rating ?? run.rating
    const riskCheck = live.riskCheck ?? run.risk_check
    const execution = live.execution ?? run.execution
    const approval = (live.approval as Record<string, unknown> | null) ?? run.approval

    const finals: Partial<Record<NodeName, string | null | undefined>> = {
      'Research Manager': investmentPlan,
      Trader: traderPlan,
      'Portfolio Manager': decision,
      'Bull Researcher': lastTurn(investmentDebate, 'bull'),
      'Bear Researcher': lastTurn(investmentDebate, 'bear'),
      'Aggressive Analyst': lastTurn(riskDebate, 'aggressive'),
      'Conservative Analyst': lastTurn(riskDebate, 'conservative'),
      'Neutral Analyst': lastTurn(riskDebate, 'neutral'),
    }
    for (const r of REPORTS) finals[r.node] = reports[r.key]

    // Evidence that a non-LLM node ran, for runs whose event history is gone.
    const evidence: Partial<Record<NodeName, boolean>> = {
      'Risk Gate': !!riskCheck,
      'Human Approval': !!approval,
      Execute: !!execution,
      Record: !!execution && terminal,
    }

    // ---- which analyst nodes belong to this run
    const selected = new Set<NodeName>(
      (run.analysts ?? []).map((a) => ANALYST_NODE[a]).filter((n): n is NodeName => n !== undefined),
    )
    const hasLive = Object.keys(live.nodes).length > 0

    const phases: PhaseView[] = PIPELINE.map((phase) => {
      const nodes: NodeView[] = []
      for (const name of phase.nodes) {
        if (phase.id === 'analysts' && selected.size > 0 && !selected.has(name) && !live.nodes[name]) continue
        const ln = live.nodes[name]
        const final = live.nodes[name]?.final ?? finals[name] ?? undefined
        let st: NodeStatus
        let note: MessageKey | undefined

        if (name === 'Human Approval' && status === 'awaiting_approval') {
          st = 'waiting'
          note = 'nodeNote.waitingApproval'
        } else if (ln) {
          st = ln.status === 'running' && terminal ? 'done' : ln.status
        } else if (final || evidence[name]) {
          st = 'done'
        } else if (name === 'Human Approval' && run.auto_approve) {
          st = 'skipped'
          note = 'nodeNote.autoApprove'
        } else if (terminal) {
          // No trace of the node: finished runs without history count as done,
          // rejected / failed ones never got there.
          st = status === 'completed' && !hasLive ? 'done' : 'skipped'
          if (st === 'skipped') note = 'nodeNote.notRun'
        } else {
          st = 'pending'
        }
        nodes.push({ name, status: st, live: ln, final: final ?? undefined, note })
      }
      return { id: phase.id, nodes, status: phaseStatus(nodes) }
    })

    let activeNode: NodeName | null = null
    for (const p of phases) for (const n of p.nodes) if (n.status === 'running') activeNode = n.name

    const pendingOrder = live.approvalRequired?.order ?? riskCheck?.order ?? null
    const needsApproval = status === 'awaiting_approval' && !approval

    const errors = [...(run.error ? [run.error] : []), ...live.errors.filter((e) => e !== run.error)]

    return {
      status,
      rating,
      terminal,
      phases,
      activeNode,
      reports,
      investmentDebate,
      riskDebate,
      investmentPlan,
      traderPlan,
      decision,
      riskCheck,
      pendingOrder,
      needsApproval,
      approval,
      execution,
      errors,
    }
  }, [run, live])
}
