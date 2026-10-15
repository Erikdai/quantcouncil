import { RUN_STATUSES, type RunStatus } from '@/api/types'
import { Badge, type BadgeTone } from '@/components/ui/Badge'
import { useT } from '@/i18n/I18nProvider'
import { normalizeRating, RATING_TONE, STATUS_TONE } from '@/lib/constants'

function isRunStatus(s: string): s is RunStatus {
  return (RUN_STATUSES as readonly string[]).includes(s)
}

export function StatusBadge({ status }: { status: RunStatus | string }) {
  const t = useT()
  if (!isRunStatus(status)) return <Badge>{status}</Badge>
  const live = status === 'running' || status === 'queued' || status === 'awaiting_approval'
  return (
    <Badge tone={STATUS_TONE[status] as BadgeTone} dot pulse={status === 'running'} title={status}>
      {t(`status.${status}`)}
      {live && <span className="sr-only">{t('status.inProgress')}</span>}
    </Badge>
  )
}

/** Rating badge: Buy/Overweight red, Underweight/Sell green (A-share convention). */
export function RatingBadge({ rating, showRaw = true }: { rating: string | null | undefined; showRaw?: boolean }) {
  const t = useT()
  if (!rating) return <span className="text-xs text-muted">—</span>
  const r = normalizeRating(rating)
  if (!r) return <Badge tone="flat">{rating}</Badge>
  const label = t(`rating.${r}`)
  return (
    <Badge tone={RATING_TONE[r] as BadgeTone} title={rating}>
      {label}
      {showRaw && label !== r && <span className="font-normal opacity-70">{r}</span>}
    </Badge>
  )
}

/** Buy = red, sell = green. */
export function SideBadge({ side }: { side: string }) {
  const t = useT()
  const s = side.toLowerCase()
  if (s !== 'buy' && s !== 'sell') return <Badge tone="muted">{side}</Badge>
  return <Badge tone={s === 'buy' ? 'up' : 'down'}>{t(`side.${s}`)}</Badge>
}
