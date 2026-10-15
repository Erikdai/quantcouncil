import { useState, type ReactNode } from 'react'
import { Loader2 } from 'lucide-react'
import type { ReportKey } from '@/api/types'
import { RatingBadge } from '@/components/common/Badges'
import { Markdown } from '@/components/common/Markdown'
import { Card } from '@/components/ui/Card'
import { Segmented, Tabs } from '@/components/ui/Controls'
import { EmptyState } from '@/components/ui/Feedback'
import type { NodeView, RunView } from '@/hooks/useRunView'
import { useT } from '@/i18n/I18nProvider'
import { normalizeRating, RATING_TONE, REPORTS, type NodeName } from '@/lib/constants'
import { cn } from '@/lib/cn'
import { DebateView } from './DebateView'

type TabId = 'reports' | 'investment' | 'plans' | 'risk' | 'decision'

const INVESTMENT_NODES: readonly NodeName[] = ['Bull Researcher', 'Bear Researcher', 'Research Manager']
const RISK_NODES: readonly NodeName[] = ['Aggressive Analyst', 'Conservative Analyst', 'Neutral Analyst']

function findNode(view: RunView, name: NodeName): NodeView | undefined {
  for (const p of view.phases) for (const n of p.nodes) if (n.name === name) return n
  return undefined
}

const isRunning = (view: RunView, name: NodeName) => findNode(view, name)?.status === 'running'

function Count({ n, total }: { n: number; total?: number }) {
  if (!n && !total) return null
  return (
    <span className="rounded-full bg-surface-3 px-1.5 text-[10px] text-muted tabular-nums">
      {total ? `${n}/${total}` : n}
    </span>
  )
}

/** Live text of a node that is still writing its deliverable. */
function Writing({ node }: { node: NodeView | undefined }) {
  const t = useT()
  if (!node || node.status !== 'running') return null
  return (
    <div>
      <div className="mb-2 flex items-center gap-1.5 text-xs text-accent">
        <Loader2 className="size-3.5 animate-spin" /> {t('reports.writing', { name: t(`node.${node.name}`) })}
      </div>
      <p className="text-sm leading-relaxed whitespace-pre-wrap text-fg-2">
        <span className="caret">{node.live?.text ?? ''}</span>
      </p>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{title}</h3>
      {children}
    </section>
  )
}

/** A deliverable, the live text while its node writes it, or a "not generated" note. */
function Deliverable({ content, view, node }: { content: string | null; view: RunView; node: NodeName }) {
  const t = useT()
  if (content) return <Markdown>{content}</Markdown>
  if (isRunning(view, node)) return <Writing node={findNode(view, node)} />
  return <p className="text-sm text-muted">{t('common.notGenerated')}</p>
}

function ReportsPane({ view }: { view: RunView }) {
  const t = useT()
  const available = REPORTS.filter((r) => view.phases[0]?.nodes.some((n) => n.name === r.node))
  const list = available.length ? available : REPORTS
  const firstReady = list.find((r) => view.reports[r.key])?.key
  const [picked, setPicked] = useState<ReportKey | null>(null)
  const current = picked ?? firstReady ?? list[0]?.key ?? 'market_report'
  const meta = REPORTS.find((r) => r.key === current)
  const content = view.reports[current]
  const node = meta ? findNode(view, meta.node) : undefined

  return (
    <div className="space-y-4">
      <Segmented
        options={list.map((r) => ({
          value: r.key,
          label: (
            <span className="inline-flex items-center gap-1">
              {t(`analyst.${r.analyst}`)}
              <span className={cn('size-1.5 rounded-full', view.reports[r.key] ? 'bg-ok' : 'bg-line-strong')} aria-hidden />
            </span>
          ),
        }))}
        value={current}
        onChange={setPicked}
      />
      {content ? (
        <Markdown>{content}</Markdown>
      ) : node?.status === 'running' ? (
        <Writing node={node} />
      ) : (
        <EmptyState
          title={t('reports.emptyTitle')}
          description={meta ? t('reports.emptyDesc', { name: t(`analyst.${meta.analyst}`) }) : undefined}
        />
      )}
    </div>
  )
}

function DecisionPane({ view }: { view: RunView }) {
  const t = useT()
  if (!view.decision) {
    return isRunning(view, 'Portfolio Manager') ? (
      <Writing node={findNode(view, 'Portfolio Manager')} />
    ) : (
      <EmptyState title={t('decision.emptyTitle')} description={t('decision.emptyDesc')} />
    )
  }
  const rating = normalizeRating(view.rating)
  const tone = rating ? RATING_TONE[rating] : undefined
  return (
    <div className="space-y-4">
      <div
        className={cn(
          'flex flex-wrap items-center gap-3 rounded-xl border p-4',
          tone === 'up' && 'border-up/30 bg-up/[0.05]',
          tone === 'down' && 'border-down/30 bg-down/[0.05]',
          tone === 'warn' && 'border-warn/30 bg-warn/[0.05]',
          (!tone || tone === 'flat') && 'border-line bg-surface-2',
        )}
      >
        <span className="text-sm text-muted">{t('decision.label')}</span>
        <span
          className={cn(
            'text-2xl font-semibold',
            tone === 'up' && 'text-up',
            tone === 'down' && 'text-down',
            tone === 'warn' && 'text-warn',
          )}
        >
          {rating ? t(`rating.${rating}`) : (view.rating ?? '—')}
        </span>
        <RatingBadge rating={view.rating} />
      </div>
      <Markdown>{view.decision}</Markdown>
    </div>
  )
}

/** Tabs: analyst reports, investment debate, plans, risk debate, final decision. */
export function RunTabs({ view }: { view: RunView }) {
  const t = useT()
  const [tab, setTab] = useState<TabId>('reports')
  const reportCount = REPORTS.filter((r) => view.reports[r.key]).length
  const analystTotal = view.phases[0]?.nodes.length ?? 4

  const items = [
    { id: 'reports' as const, label: t('tabs.reports'), badge: <Count n={reportCount} total={analystTotal} /> },
    { id: 'investment' as const, label: t('tabs.investment'), badge: <Count n={view.investmentDebate.length} /> },
    { id: 'plans' as const, label: t('tabs.plans') },
    { id: 'risk' as const, label: t('tabs.risk'), badge: <Count n={view.riskDebate.length} /> },
    { id: 'decision' as const, label: t('tabs.decision') },
  ]

  return (
    <Card className="min-w-0">
      <Tabs items={items} value={tab} onChange={setTab} ariaLabel={t('tabs.aria')} />
      {/* Reports run to thousands of words: scroll inside the card instead of stretching the page. */}
      <div className="max-h-[min(75vh,760px)] overflow-y-auto p-4 sm:p-5">
        {tab === 'reports' && <ReportsPane view={view} />}

        {tab === 'investment' && (
          <DebateView
            turns={view.investmentDebate}
            verdict={view.investmentPlan}
            verdictTitle={t('debate.verdictTitle')}
            running={INVESTMENT_NODES.some((n) => isRunning(view, n))}
            emptyText={t('debate.investmentEmpty')}
          />
        )}

        {tab === 'plans' && (
          <div className="space-y-6">
            <Section title={t('plans.investment')}>
              <Deliverable content={view.investmentPlan} view={view} node="Research Manager" />
            </Section>
            <Section title={t('plans.trader')}>
              <Deliverable content={view.traderPlan} view={view} node="Trader" />
            </Section>
          </div>
        )}

        {tab === 'risk' && (
          <DebateView
            turns={view.riskDebate}
            running={RISK_NODES.some((n) => isRunning(view, n))}
            emptyText={t('debate.riskEmpty')}
          />
        )}

        {tab === 'decision' && <DecisionPane view={view} />}
      </div>
    </Card>
  )
}
