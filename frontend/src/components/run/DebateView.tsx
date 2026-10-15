import { Gavel, Scale, ShieldCheck, TrendingDown, TrendingUp, Zap, type LucideIcon } from 'lucide-react'
import { Markdown } from '@/components/common/Markdown'
import { EmptyState } from '@/components/ui/Feedback'
import { useT } from '@/i18n/I18nProvider'
import { cn } from '@/lib/cn'
import type { DebateSide, DebateTurn } from '@/lib/debate'

interface SideStyle {
  align: 'left' | 'right' | 'center'
  bubble: string
  avatar: string
  icon: LucideIcon
}

// Bull / aggressive lean red (up), bear / conservative lean green (down): A-share colours.
const SIDE_STYLE: Record<DebateSide, SideStyle> = {
  bull: { align: 'left', bubble: 'border-up/25 bg-up/[0.05]', avatar: 'bg-up/15 text-up', icon: TrendingUp },
  bear: { align: 'right', bubble: 'border-down/25 bg-down/[0.05]', avatar: 'bg-down/15 text-down', icon: TrendingDown },
  aggressive: { align: 'left', bubble: 'border-up/25 bg-up/[0.05]', avatar: 'bg-up/15 text-up', icon: Zap },
  conservative: {
    align: 'right',
    bubble: 'border-down/25 bg-down/[0.05]',
    avatar: 'bg-down/15 text-down',
    icon: ShieldCheck,
  },
  neutral: { align: 'center', bubble: 'border-line bg-surface-2', avatar: 'bg-surface-3 text-fg-2', icon: Scale },
  judge: { align: 'center', bubble: 'border-accent/30 bg-accent/[0.05]', avatar: 'bg-accent/15 text-accent', icon: Gavel },
  other: { align: 'left', bubble: 'border-line bg-surface-2', avatar: 'bg-surface-3 text-fg-2', icon: Scale },
}

function Bubble({ turn, round }: { turn: DebateTurn; round: number }) {
  const t = useT()
  const s = SIDE_STYLE[turn.side]
  const Icon = s.icon
  return (
    <div className={cn('flex gap-2.5', s.align === 'right' && 'flex-row-reverse', s.align === 'center' && 'mx-auto max-w-3xl')}>
      <div className={cn('mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full', s.avatar)}>
        <Icon className="size-4" />
      </div>
      <div className={cn('min-w-0', s.align === 'center' ? 'flex-1' : 'max-w-[88%] sm:max-w-[80%]')}>
        <div className={cn('mb-1 flex items-center gap-2 text-xs text-muted', s.align === 'right' && 'justify-end')}>
          <span className="font-medium text-fg-2">{t(`debate.side.${turn.side}`)}</span>
          {turn.speaker && <span className="font-mono text-[10px]">{turn.speaker}</span>}
          <span>{t('pipeline.round', { n: round })}</span>
        </div>
        <div
          className={cn('rounded-2xl border px-3.5 py-2.5', s.bubble, s.align === 'right' ? 'rounded-tr-sm' : 'rounded-tl-sm')}
        >
          <Markdown className="text-[13px]">{turn.content}</Markdown>
        </div>
      </div>
    </div>
  )
}

export function DebateView({
  turns,
  verdict,
  verdictTitle,
  running,
  emptyText,
}: {
  turns: DebateTurn[]
  verdict?: string | null
  verdictTitle?: string
  running?: boolean
  emptyText: string
}) {
  const t = useT()
  if (turns.length === 0 && !verdict) {
    return (
      <EmptyState
        title={running ? t('debate.running') : t('debate.empty')}
        description={running ? t('debate.runningDesc') : emptyText}
      />
    )
  }

  // Round number = how many times this side has spoken so far.
  const counts = new Map<DebateSide, number>()
  return (
    <div className="space-y-4">
      {turns.map((turn, i) => {
        const round = (counts.get(turn.side) ?? 0) + 1
        counts.set(turn.side, round)
        return <Bubble key={i} turn={turn} round={round} />
      })}
      {verdict && (
        <div className="rounded-xl border border-accent/30 bg-accent/[0.04] p-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-accent">
            <Gavel className="size-4" />
            {verdictTitle ?? t('debate.side.judge')}
          </div>
          <Markdown>{verdict}</Markdown>
        </div>
      )}
    </div>
  )
}
