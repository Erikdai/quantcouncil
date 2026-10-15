import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { History, RotateCw } from 'lucide-react'
import type { RunStatus } from '@/api/types'
import { RatingBadge, StatusBadge } from '@/components/common/Badges'
import { Button } from '@/components/ui/Button'
import { Card, CardHeader } from '@/components/ui/Card'
import { Segmented } from '@/components/ui/Controls'
import { EmptyState, ErrorState, SkeletonRows } from '@/components/ui/Feedback'
import { isTerminal, useRuns } from '@/hooks/api'
import { useT } from '@/i18n/I18nProvider'
import { fmtDate, fmtDateTime, fmtRelative } from '@/lib/format'
import { cn } from '@/lib/cn'

type Filter = 'all' | RunStatus

const FILTERS: readonly Filter[] = ['all', 'running', 'awaiting_approval', 'completed', 'failed']

export function RecentRuns() {
  const t = useT()
  const [filter, setFilter] = useState<Filter>('all')
  const { data, isPending, isError, error, refetch, isFetching } = useRuns(filter === 'all' ? null : filter, 30)
  const navigate = useNavigate()
  const live = data?.some((r) => !isTerminal(r.status)) ?? false
  const options = FILTERS.map((f) => ({ value: f, label: f === 'all' ? t('runs.all') : t(`status.${f}`) }))

  return (
    <Card>
      <CardHeader
        title={t('runs.title')}
        icon={<History />}
        subtitle={live ? t('runs.live') : t('runs.hint')}
        actions={
          <>
            <div className="hidden sm:block">
              <Segmented options={options} value={filter} onChange={setFilter} />
            </div>
            <Button
              size="icon"
              variant="ghost"
              aria-label={t('common.refresh')}
              onClick={() => void refetch()}
              icon={<RotateCw className={cn('size-4', isFetching && 'animate-spin')} />}
            />
          </>
        }
      />
      <div className="border-b border-line px-4 py-2 sm:hidden">
        <Segmented options={options} value={filter} onChange={setFilter} />
      </div>

      {isPending ? (
        <SkeletonRows rows={6} className="p-4" />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : data.length === 0 ? (
        <EmptyState title={t('runs.emptyTitle')} description={t('runs.emptyDesc')} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-muted">
                <th className="px-4 py-2 font-medium">{t('runs.colStock')}</th>
                <th className="hidden px-3 py-2 font-medium sm:table-cell">{t('runs.colDate')}</th>
                <th className="px-3 py-2 font-medium">{t('runs.colStatus')}</th>
                <th className="px-3 py-2 font-medium">{t('runs.colRating')}</th>
                <th className="hidden px-4 py-2 text-right font-medium md:table-cell">{t('runs.colCreated')}</th>
              </tr>
            </thead>
            <tbody>
              {data.map((r) => (
                <tr
                  key={r.id}
                  onClick={() => navigate(`/runs/${r.id}`)}
                  className="cursor-pointer border-b border-line/70 transition last:border-0 hover:bg-surface-2"
                >
                  <td className="px-4 py-2.5">
                    <Link
                      to={`/runs/${r.id}`}
                      onClick={(e) => e.stopPropagation()}
                      className="block min-w-0 hover:text-accent"
                    >
                      <span className="font-mono text-[13px] font-medium text-fg">{r.ticker}</span>
                      <span className="ml-2 text-xs text-muted">{r.name ?? ''}</span>
                      <span className="block text-[11px] text-muted sm:hidden">{fmtDate(r.trade_date)}</span>
                    </Link>
                  </td>
                  <td className="hidden px-3 py-2.5 font-mono text-xs text-fg-2 sm:table-cell">{fmtDate(r.trade_date)}</td>
                  <td className="px-3 py-2.5">
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="px-3 py-2.5">
                    <RatingBadge rating={r.rating} showRaw={false} />
                  </td>
                  <td
                    className="hidden px-4 py-2.5 text-right text-xs whitespace-nowrap text-muted md:table-cell"
                    title={fmtDateTime(r.created_at)}
                  >
                    {fmtRelative(r.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
