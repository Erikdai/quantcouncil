import { ExternalLink, FlaskConical } from 'lucide-react'
import type { EvalResultOut, RunOut } from '@/api/types'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { useEvaluateRun } from '@/hooks/api'
import { useI18n, useT } from '@/i18n/I18nProvider'
import { cn } from '@/lib/cn'
import { fmtDateTime } from '@/lib/format'

const MAX = 5

function ScoreBar({ name, score }: { name: string; score: number }) {
  const { tx } = useI18n()
  const label = tx(`criteria.${name}`, name)
  const pct = Math.max(0, Math.min(1, score / MAX)) * 100
  const color = score >= 4 ? 'bg-ok' : score >= 3 ? 'bg-accent' : score >= 2 ? 'bg-warn' : 'bg-up'
  return (
    <div className="grid grid-cols-[6.5rem_1fr_2.5rem] items-center gap-2 text-xs">
      <span className="truncate text-fg-2" title={name}>
        {label}
      </span>
      <div
        className="relative h-2 overflow-hidden rounded-full bg-surface-3"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={MAX}
        aria-valuenow={score}
        aria-label={label}
      >
        <div className={cn('h-full rounded-full transition-[width] duration-500', color)} style={{ width: `${pct}%` }} />
        {/* tick marks at 1..4 */}
        {[1, 2, 3, 4].map((tick) => (
          <span key={tick} className="absolute top-0 h-full w-px bg-surface/80" style={{ left: `${(tick / MAX) * 100}%` }} />
        ))}
      </div>
      <span className="text-right font-mono text-fg tabular-nums">{score.toFixed(1)}</span>
    </div>
  )
}

function EvalResult({ result }: { result: EvalResultOut }) {
  const t = useT()
  return (
    <div className="space-y-2.5 rounded-lg border border-line p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-fg-2">{result.evaluator}</span>
        <Badge tone={result.passed ? 'ok' : 'warn'}>{result.passed ? t('eval.passed') : t('eval.failed')}</Badge>
        <span className="ml-auto text-[11px] text-muted">{fmtDateTime(result.created_at)}</span>
      </div>
      <div className="space-y-1.5">
        {Object.entries(result.scores).map(([k, v]) => (
          <ScoreBar key={k} name={k} score={v} />
        ))}
      </div>
      {/* the judge's comment is model output and shown as-is */}
      {result.comment && <p className="text-xs leading-relaxed text-muted">{result.comment}</p>}
    </div>
  )
}

/** LLM-as-judge scoring of the run's reports + link to the Langfuse trace. */
export function EvalPanel({ run, terminal }: { run: RunOut; terminal: boolean }) {
  const t = useT()
  const evaluate = useEvaluateRun(run.id)
  const evals = [...(run.evals ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at))

  return (
    <Card>
      <CardHeader
        title={t('eval.title')}
        icon={<FlaskConical />}
        subtitle={t('eval.subtitle')}
        actions={
          <Button
            size="sm"
            variant="primary"
            loading={evaluate.isPending}
            disabled={!terminal}
            title={terminal ? undefined : t('eval.afterDone')}
            onClick={() => evaluate.mutate()}
          >
            {evals.length ? t('eval.rerun') : t('eval.run')}
          </Button>
        }
      />
      <CardBody className="space-y-3">
        {evals.length === 0 ? (
          <p className="text-xs text-muted">{terminal ? t('eval.none') : t('eval.waiting')}</p>
        ) : (
          evals.map((e) => <EvalResult key={e.id} result={e} />)
        )}
        {run.trace_url && (
          <a
            href={run.trace_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-xs text-accent hover:underline"
          >
            <ExternalLink className="size-3.5" />
            {t('eval.trace')}
          </a>
        )}
      </CardBody>
    </Card>
  )
}
