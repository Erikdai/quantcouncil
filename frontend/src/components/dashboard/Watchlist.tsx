import { useState, type FormEvent } from 'react'
import { Play, Plus, Star, X } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardHeader } from '@/components/ui/Card'
import { Input } from '@/components/ui/Controls'
import { EmptyState, ErrorState, SkeletonRows } from '@/components/ui/Feedback'
import { useAddWatch, useRemoveWatch, useWatchlist } from '@/hooks/api'
import { useT } from '@/i18n/I18nProvider'
import { toast } from '@/lib/toast'

/** Watchlist card; the scheduler scans these names after every close. */
export function Watchlist({ onAnalyze }: { onAnalyze: (ticker: string) => void }) {
  const t = useT()
  const { data, isPending, isError, error, refetch } = useWatchlist()
  const add = useAddWatch()
  const remove = useRemoveWatch()
  const [ticker, setTicker] = useState('')

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    const value = ticker.trim()
    if (!value) return
    add.mutate(value, {
      onSuccess: (item) => {
        setTicker('')
        toast.success(t('watch.added'), `${item.ticker} ${item.name ?? ''}`)
      },
    })
  }

  return (
    <Card>
      <CardHeader title={t('watch.title')} icon={<Star />} subtitle={t('watch.subtitle')} />
      <form onSubmit={onSubmit} className="flex gap-2 border-b border-line p-3">
        <Input
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder={t('watch.placeholder')}
          aria-label={t('watch.inputAria')}
          className="font-mono"
          autoComplete="off"
        />
        <Button type="submit" loading={add.isPending} icon={<Plus className="size-4" />} disabled={!ticker.trim()}>
          {t('watch.add')}
        </Button>
      </form>

      {isPending ? (
        <SkeletonRows rows={3} className="p-3" />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : data.length === 0 ? (
        <EmptyState icon={<Star />} title={t('watch.emptyTitle')} description={t('watch.emptyDesc')} />
      ) : (
        <ul className="max-h-80 divide-y divide-line overflow-y-auto">
          {data.map((w) => {
            const removing = remove.isPending && remove.variables === w.ticker
            return (
              <li key={w.ticker} className="group flex items-center gap-2 px-4 py-2">
                <div className="min-w-0 flex-1">
                  <span className="font-mono text-[13px] font-medium text-fg">{w.ticker}</span>
                  <span className="ml-2 text-xs text-muted">{w.name ?? ''}</span>
                  {!w.enabled && (
                    <Badge className="ml-2" tone="muted">
                      {t('watch.paused')}
                    </Badge>
                  )}
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => onAnalyze(w.ticker)}
                  icon={<Play className="size-3.5" />}
                  title={t('watch.analyzeTitle')}
                >
                  {t('watch.analyze')}
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label={t('watch.remove', { ticker: w.ticker })}
                  loading={removing}
                  onClick={() => remove.mutate(w.ticker)}
                  icon={<X className="size-4" />}
                  className="text-muted hover:text-up"
                />
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}
