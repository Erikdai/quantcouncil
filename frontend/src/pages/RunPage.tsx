import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { AlertOctagon, ArrowLeft, BrainCircuit, CandlestickChart, Cpu, RotateCw, Workflow } from 'lucide-react'
import { ApiError } from '@/api/client'
import { useRunEvents, type ConnectionState } from '@/api/sse'
import type { RunEvent, RunEventType, RunOut } from '@/api/types'
import { RatingBadge, StatusBadge } from '@/components/common/Badges'
import { ExportMenu } from '@/components/common/ExportMenu'
import { KlineChart } from '@/components/common/KlineChart'
import { ApprovalCard } from '@/components/run/ApprovalCard'
import { EvalPanel } from '@/components/run/EvalPanel'
import { ExecutionCard } from '@/components/run/ExecutionCard'
import { PipelineTimeline } from '@/components/run/PipelineTimeline'
import { RiskCheckPanel } from '@/components/run/RiskCheckPanel'
import { RunTabs } from '@/components/run/RunTabs'
import { Badge } from '@/components/ui/Badge'
import { Button, buttonClass } from '@/components/ui/Button'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/Feedback'
import { isTerminal, qk, useKline, useRun } from '@/hooks/api'
import { useRunView, type RunView } from '@/hooks/useRunView'
import { useI18n, useT } from '@/i18n/I18nProvider'
import { providerShort } from '@/lib/constants'
import { fmtDate, fmtDateTime, fmtDuration } from '@/lib/format'

/** Events after which the persisted run row has meaningfully changed. */
const REFRESH_ON: ReadonlySet<RunEventType> = new Set<RunEventType>([
  'status',
  'decision',
  'risk_check',
  'approval_required',
  'approval',
  'execution',
  'error',
])

function ConnectionPill({
  state,
  terminal,
  onReconnect,
}: {
  state: ConnectionState
  terminal: boolean
  onReconnect: () => void
}) {
  const t = useT()
  if (state === 'open' && !terminal)
    return (
      <Badge tone="accent" dot pulse title={t('run.connLiveTitle')}>
        {t('run.connLive')}
      </Badge>
    )
  if (state === 'connecting') return <Badge tone="muted">{t('run.connConnecting')}</Badge>
  if (state === 'reconnecting') return <Badge tone="warn">{t('run.connReconnecting')}</Badge>
  if (state === 'error')
    return (
      <Button size="sm" variant="ghost" onClick={onReconnect} icon={<RotateCw className="size-3.5" />}>
        {terminal ? t('run.connReplay') : t('run.connLost')}
      </Button>
    )
  return null
}

function RunHeader({
  run,
  status,
  rating,
  children,
}: {
  run: RunOut
  status: RunOut['status']
  rating: string | null
  children?: ReactNode
}) {
  const { t, tx } = useI18n()
  return (
    <div className="mb-5">
      <Link to="/" className="mb-2 inline-flex items-center gap-1 text-xs text-muted hover:text-accent">
        <ArrowLeft className="size-3.5" /> {t('nav.dashboard')}
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 basis-96">
          <h1 className="flex flex-wrap items-baseline gap-x-2 text-xl font-semibold tracking-tight text-fg">
            <span className="font-mono">{run.ticker}</span>
            {run.name && <span>{run.name}</span>}
            <span className="text-sm font-normal text-muted">{run.market}</span>
          </h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
            <span>
              {t('run.tradeDate')} <span className="font-mono text-fg-2">{fmtDate(run.trade_date)}</span>
            </span>
            <span>{t('run.created', { time: fmtDateTime(run.created_at) })}</span>
            {run.finished_at && <span>{t('run.elapsed', { d: fmtDuration(run.created_at, run.finished_at) })}</span>}
            <span className="flex flex-wrap gap-1">
              {(run.analysts ?? []).map((a) => (
                <span key={a} className="rounded bg-surface-2 px-1.5 py-0.5 text-[11px] text-fg-2">
                  {tx(`analyst.${a}`, a)}
                </span>
              ))}
            </span>
            {run.auto_approve && <Badge tone="muted">{t('runForm.autoApprove')}</Badge>}
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
          {run.llm?.provider && (
            <Badge
              tone="muted"
              title={t('run.modelTitle', { quick: run.llm.quick_model ?? '—', deep: run.llm.deep_model ?? '—' })}
            >
              <Cpu className="size-3" />
              {providerShort(run.llm.provider)}
              {run.llm.deep_model && <span className="font-mono font-normal">· {run.llm.deep_model}</span>}
            </Badge>
          )}
          <StatusBadge status={status} />
          {rating && <RatingBadge rating={rating} />}
          {children}
          {isTerminal(status) && <ExportMenu target={{ kind: 'run', runId: run.id }} size="sm" />}
        </div>
      </div>
    </div>
  )
}

function ChartCard({ run, rating }: { run: RunOut; rating: string | null }) {
  const t = useT()
  const { data, isPending, isError, error, refetch } = useKline(run.ticker, run.trade_date)
  return (
    <Card>
      <CardHeader
        title={t('chart.title')}
        icon={<CandlestickChart />}
        subtitle={t('chart.subtitle', { date: fmtDate(run.trade_date) })}
      />
      <div className="px-2 pt-2 pb-1">
        {isPending ? (
          <Skeleton className="m-2 h-[300px]" />
        ) : isError ? (
          <ErrorState error={error} title={t('chart.failed')} onRetry={() => void refetch()} />
        ) : data.bars.length === 0 ? (
          <EmptyState icon={<CandlestickChart />} title={t('chart.empty')} />
        ) : (
          <>
            <p className="px-3 pb-2 text-xs text-muted">
              {data.source} · {data.currency} · {data.timezone} · {t('chart.latestBar')}: {data.latest_bar_date}
              {' · '}{t('chart.adjusted')}
            </p>
            <KlineChart bars={data.bars} markerDate={run.trade_date} rating={rating} height={320} />
          </>
        )}
      </div>
    </Card>
  )
}

function PipelineCard({ view }: { view: RunView }) {
  const t = useT()
  const subtitle = view.activeNode
    ? t('pipeline.running', { name: t(`node.${view.activeNode}`) })
    : view.status === 'awaiting_approval'
      ? t('pipeline.awaiting')
      : view.terminal
        ? t('pipeline.ended')
        : view.status === 'queued'
          ? t('pipeline.queued')
          : t('pipeline.inProgress')
  return (
    <Card className="xl:sticky xl:top-20">
      <CardHeader title={t('pipeline.title')} icon={<Workflow />} subtitle={subtitle} />
      <CardBody className="max-h-[70vh] overflow-y-auto xl:max-h-[calc(100dvh-10rem)]">
        <PipelineTimeline phases={view.phases} activeNode={view.activeNode} />
      </CardBody>
    </Card>
  )
}

function PageSkeleton() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-4 w-20" />
      <Skeleton className="h-8 w-72" />
      <div className="grid gap-5 xl:grid-cols-[400px_1fr]">
        <Skeleton className="h-[480px]" />
        <div className="space-y-5">
          <Skeleton className="h-[340px]" />
          <Skeleton className="h-[260px]" />
        </div>
      </div>
    </div>
  )
}

export default function RunPage() {
  const t = useT()
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const runQ = useRun(id)
  const notFound = runQ.error instanceof ApiError && runQ.error.status === 404

  // Debounced refetch of the run row while events stream in.
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])
  const onEvent = useCallback(
    (ev: RunEvent) => {
      if (!REFRESH_ON.has(ev.type)) return
      clearTimeout(timer.current)
      timer.current = setTimeout(() => void qc.invalidateQueries({ queryKey: qk.run(id) }), 600)
    },
    [qc, id],
  )
  const onDone = useCallback(() => {
    void qc.invalidateQueries({ queryKey: qk.run(id) })
    void qc.invalidateQueries({ queryKey: qk.runsAll })
    void qc.invalidateQueries({ queryKey: ['portfolio'] })
    void qc.invalidateQueries({ queryKey: ['orders'] })
  }, [qc, id])

  const { state: live, reconnect } = useRunEvents(id, { enabled: !!id && !notFound, onEvent, onDone })
  const view = useRunView(runQ.data, live)
  // Hide the approval card as soon as our POST succeeds, even before the stream catches up.
  const [approvalSent, setApprovalSent] = useState(false)

  if (runQ.isPending) return <PageSkeleton />
  if (runQ.isError || !view) {
    return notFound ? (
      <EmptyState
        title={t('run.notFoundTitle')}
        description={t('run.notFoundDesc', { id })}
        action={
          <Link to="/" className={buttonClass('primary')}>
            {t('notFound.back')}
          </Link>
        }
      />
    ) : (
      <ErrorState error={runQ.error} onRetry={() => void runQ.refetch()} />
    )
  }

  const run = runQ.data

  return (
    <>
      <RunHeader run={run} status={view.status} rating={view.rating}>
        <ConnectionPill state={live.connection} terminal={view.terminal} onReconnect={reconnect} />
      </RunHeader>

      {view.errors.length > 0 && (
        <div role="alert" className="mb-5 flex gap-3 rounded-xl border border-up/30 bg-up/[0.05] p-4">
          <AlertOctagon className="mt-0.5 size-4 shrink-0 text-up" />
          <div className="min-w-0 space-y-1 text-sm">
            <p className="font-medium text-fg">{t('run.errorTitle')}</p>
            {view.errors.map((e, i) => (
              <p key={i} className="font-mono text-xs break-words text-fg-2">
                {e}
              </p>
            ))}
          </div>
        </div>
      )}

      {view.needsApproval && !approvalSent && (
        <div className="mb-5">
          <ApprovalCard
            key={`${view.pendingOrder?.quantity ?? 'none'}`}
            onSubmitted={() => setApprovalSent(true)}
            runId={run.id}
            order={view.pendingOrder}
            riskCheck={view.riskCheck}
          />
        </div>
      )}

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,400px)_minmax(0,1fr)]">
        <PipelineCard view={view} />

        <div className="min-w-0 space-y-5">
          <ChartCard run={run} rating={view.rating} />
          {/* Outcome first: the order the risk gate checked and its fill, then the analysis. */}
          {view.riskCheck && <RiskCheckPanel check={view.riskCheck} />}
          {view.execution && <ExecutionCard execution={view.execution} />}
          <RunTabs view={view} />
          {live.memory && (live.memory.lessons > 0 || live.memory.note) && (
            <Card>
              <CardHeader
                title={t('run.memoryTitle')}
                icon={<BrainCircuit />}
                subtitle={t('run.memorySubtitle', { n: live.memory.lessons })}
              />
              {live.memory.note && <CardBody className="text-sm text-fg-2">{live.memory.note}</CardBody>}
            </Card>
          )}
          <EvalPanel run={run} terminal={view.terminal} />
        </div>
      </div>
    </>
  )
}
