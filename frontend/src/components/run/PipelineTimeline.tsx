import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { CheckCircle2, ChevronDown, Circle, Hourglass, Loader2, MinusCircle, Wrench } from 'lucide-react'
import type { ToolCallState } from '@/api/sse'
import { Markdown } from '@/components/common/Markdown'
import type { NodeStatus, NodeView, PhaseView } from '@/hooks/useRunView'
import { useT } from '@/i18n/I18nProvider'
import type { NodeName } from '@/lib/constants'
import { cn } from '@/lib/cn'
import { fmtDuration } from '@/lib/format'

const STATUS_ICON: Record<NodeStatus, { icon: typeof Circle; className: string }> = {
  pending: { icon: Circle, className: 'text-line-strong' },
  running: { icon: Loader2, className: 'text-accent animate-spin' },
  waiting: { icon: Hourglass, className: 'text-warn' },
  done: { icon: CheckCircle2, className: 'text-ok' },
  skipped: { icon: MinusCircle, className: 'text-muted/60' },
}

function StatusIcon({ status }: { status: NodeStatus }) {
  const t = useT()
  const { icon: Icon, className } = STATUS_ICON[status]
  return <Icon className={cn('size-4 shrink-0', className)} aria-label={t(`nodeStatus.${status}`)} />
}

/** Calls grouped by tool name, in order of first use (analysts often call one tool 10+ times). */
function groupByTool(tools: ToolCallState[]): Array<{ tool: string; calls: ToolCallState[] }> {
  const groups = new Map<string, ToolCallState[]>()
  for (const call of tools) groups.set(call.tool, [...(groups.get(call.tool) ?? []), call])
  return [...groups].map(([tool, calls]) => ({ tool, calls }))
}

function ToolCalls({ tools }: { tools: ToolCallState[] }) {
  const [open, setOpen] = useState<string | null>(null)
  if (tools.length === 0) return null
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {groupByTool(tools).map(({ tool, calls }) => {
        const running = calls.some((c) => c.preview === undefined)
        const expanded = open === tool
        return (
          <div key={tool} className={cn(expanded && 'w-full')}>
            <button
              type="button"
              onClick={() => setOpen(expanded ? null : tool)}
              aria-expanded={expanded}
              className={cn(
                'inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 font-mono text-[11px] transition',
                running
                  ? 'border-accent/40 bg-accent/5 text-accent'
                  : 'border-line bg-surface-2 text-fg-2 hover:border-line-strong',
              )}
            >
              {running ? <Loader2 className="size-3 animate-spin" /> : <Wrench className="size-3" />}
              {tool}
              {calls.length > 1 && <span className="text-muted">×{calls.length}</span>}
            </button>
            {expanded && (
              <ol className="mt-1.5 max-h-72 space-y-2 overflow-auto rounded-lg border border-line bg-surface-2 p-2 font-mono text-[11px]">
                {calls.map((call, i) => (
                  <li key={i} className="space-y-1">
                    <div>
                      <span className="text-muted">{calls.length > 1 ? `#${i + 1} args ` : 'args '}</span>
                      <span className="break-all text-fg-2">{JSON.stringify(call.args)}</span>
                    </div>
                    {call.preview !== undefined && (
                      <pre className="max-h-32 overflow-auto break-words whitespace-pre-wrap text-fg-2">{call.preview}</pre>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </div>
        )
      })}
    </div>
  )
}

/** Live LLM output: plain text while tokens stream, auto-scrolled unless the user scrolled up. */
function StreamingText({ text }: { text: string }) {
  const t = useT()
  const ref = useRef<HTMLDivElement>(null)
  const stick = useRef(true)

  useLayoutEffect(() => {
    const el = ref.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [text])

  return (
    <div
      ref={ref}
      onScroll={(e) => {
        const el = e.currentTarget
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
      }}
      className="mt-2 max-h-64 overflow-y-auto rounded-lg border border-accent/20 bg-accent/[0.03] p-2.5 text-xs leading-relaxed whitespace-pre-wrap text-fg-2"
    >
      <span className="caret">{text || t('pipeline.thinking')}</span>
    </div>
  )
}

const CLAMP_PX = 96

// Only debaters speak in rounds; a repeated start on other nodes is a retry, not a round.
const DEBATERS: ReadonlySet<NodeName> = new Set<NodeName>([
  'Bull Researcher',
  'Bear Researcher',
  'Aggressive Analyst',
  'Conservative Analyst',
  'Neutral Analyst',
])

/** Clamped preview that only fades and offers "show more" when the content really overflows. */
function Collapsible({ children }: { children: ReactNode }) {
  const t = useT()
  const innerRef = useRef<HTMLDivElement>(null)
  const [expanded, setExpanded] = useState(false)
  const [overflows, setOverflows] = useState(false)

  useLayoutEffect(() => {
    const inner = innerRef.current
    if (!inner) return
    const check = () => setOverflows(inner.scrollHeight > CLAMP_PX + 4)
    check()
    const ro = new ResizeObserver(check)
    ro.observe(inner)
    return () => ro.disconnect()
  }, [])

  const clamped = overflows && !expanded
  return (
    <div className="mt-1.5">
      <div
        className="relative overflow-hidden rounded-lg border border-line bg-surface-2/50 px-3 py-2"
        style={clamped ? { maxHeight: CLAMP_PX } : undefined}
      >
        <div ref={innerRef}>{children}</div>
        {clamped && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-surface to-transparent" />
        )}
      </div>
      {(overflows || expanded) && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="mt-1 inline-flex items-center gap-0.5 text-[11px] text-muted hover:text-accent"
        >
          <ChevronDown className={cn('size-3 transition', expanded && 'rotate-180')} />
          {expanded ? t('common.collapse') : t('common.expand')}
        </button>
      )}
    </div>
  )
}

function NodeRow({ node, isActive }: { node: NodeView; isActive: boolean }) {
  const t = useT()
  const live = node.live
  const streaming = node.status === 'running'
  const body = node.final ?? (live?.text || undefined)
  const duration = live?.startedAt && live.endedAt ? fmtDuration(live.startedAt, live.endedAt) : null
  const label = t(`node.${node.name}`)

  return (
    <li className={cn('relative pl-6', isActive && 'animate-fade-in')} aria-current={isActive ? 'step' : undefined}>
      <span className="absolute top-0.5 left-0 bg-surface">
        <StatusIcon status={node.status} />
      </span>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
        <span className={cn('text-sm', node.status === 'skipped' ? 'text-muted' : 'font-medium text-fg')}>{label}</span>
        {label !== node.name && <span className="font-mono text-[10px] text-muted">{node.name}</span>}
        {live && live.turns > 1 && DEBATERS.has(node.name) && (
          <span className="text-[11px] text-muted">{t('pipeline.round', { n: live.turns })}</span>
        )}
        {duration && <span className="ml-auto text-[11px] text-muted tabular-nums">{duration}</span>}
        {node.note && <span className="text-[11px] text-muted">· {t(node.note)}</span>}
      </div>

      {live?.error && (
        <p className="mt-1.5 rounded-md border-l-2 border-up bg-up/[0.06] px-2 py-1 font-mono text-[11px] break-words text-up">
          {live.error}
        </p>
      )}

      {live && <ToolCalls tools={live.tools} />}

      {streaming && !node.final && <StreamingText text={live?.text ?? ''} />}

      {!streaming && body && (
        <Collapsible>
          {node.final ? (
            <Markdown className="text-xs [&_h1]:text-sm [&_h2]:text-sm [&_h3]:text-xs">{node.final}</Markdown>
          ) : (
            <p className="text-xs whitespace-pre-wrap text-fg-2">{body}</p>
          )}
        </Collapsible>
      )}
    </li>
  )
}

/** Vertical pipeline of the agent graph, grouped by phase, driven by `node` / `token` events. */
export function PipelineTimeline({ phases, activeNode }: { phases: PhaseView[]; activeNode: string | null }) {
  const t = useT()
  return (
    <ol className="space-y-4">
      {phases.map((phase, idx) => (
        <li key={phase.id} className="relative">
          <div className="mb-2 flex items-center gap-2">
            <span
              className={cn(
                'flex size-5 items-center justify-center rounded-full text-[10px] font-semibold',
                phase.status === 'done' && 'bg-ok/15 text-ok',
                phase.status === 'running' && 'bg-accent text-accent-fg',
                phase.status === 'waiting' && 'bg-warn/15 text-warn',
                (phase.status === 'pending' || phase.status === 'skipped') && 'bg-surface-3 text-muted',
              )}
            >
              {idx + 1}
            </span>
            <span
              className={cn(
                'text-xs font-semibold tracking-wide',
                phase.status === 'pending' || phase.status === 'skipped' ? 'text-muted' : 'text-fg',
              )}
            >
              {t(`phase.${phase.id}`)}
            </span>
          </div>
          <ol className="ml-2.5 space-y-3 border-l border-line pb-1 pl-3">
            {phase.nodes.map((n) => (
              <NodeRow key={n.name} node={n} isActive={n.name === activeNode} />
            ))}
          </ol>
        </li>
      ))}
    </ol>
  )
}
