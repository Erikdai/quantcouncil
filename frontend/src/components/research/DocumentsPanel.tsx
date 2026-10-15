import { useEffect, useState } from 'react'
import { DatabaseZap, ExternalLink, FileText } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, SkeletonRows } from '@/components/ui/Feedback'
import { useDocuments, useIngest } from '@/hooks/api'
import { useT } from '@/i18n/I18nProvider'
import { fmtDate } from '@/lib/format'
import { toast } from '@/lib/toast'
import { DocTypeBadge } from './CitationCard'

const POLL_MS = 90_000

/** Ingested documents for the ticker + async ingest of announcements / research reports. */
export function DocumentsPanel({ ticker }: { ticker: string }) {
  const t = useT()
  const scope = ticker.trim() || null
  const [polling, setPolling] = useState(false)
  const docs = useDocuments(scope, polling)
  const ingest = useIngest()

  // Poll the list for a while after an ingest is queued.
  useEffect(() => {
    if (!polling) return
    const timer = setTimeout(() => setPolling(false), POLL_MS)
    return () => clearTimeout(timer)
  }, [polling])

  const onIngest = () => {
    if (!scope) return
    ingest.mutate(
      { ticker: scope, kinds: ['announcement', 'research'], limit: 10 },
      {
        onSuccess: (res) => {
          toast.success(t('docs.queued'), t('docs.queuedDesc', { id: res.task_id }))
          setPolling(true)
        },
      },
    )
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
        <p className="text-xs text-muted">{scope ? t('docs.forTicker', { t: scope }) : t('docs.all')}</p>
        <Button
          size="sm"
          variant="primary"
          icon={<DatabaseZap className="size-3.5" />}
          loading={ingest.isPending}
          disabled={!scope}
          title={scope ? t('docs.ingestTitle') : t('docs.needTicker')}
          onClick={onIngest}
        >
          {t('docs.ingest')}
        </Button>
      </div>
      {polling && <p className="border-b border-line bg-accent/5 px-4 py-1.5 text-[11px] text-accent">{t('docs.polling')}</p>}

      {docs.isPending ? (
        <SkeletonRows rows={5} className="p-4" />
      ) : docs.isError ? (
        <ErrorState error={docs.error} onRetry={() => void docs.refetch()} />
      ) : docs.data.length === 0 ? (
        <EmptyState
          icon={<FileText />}
          title={t('docs.emptyTitle')}
          description={scope ? t('docs.emptyTicker') : t('docs.emptyAll')}
        />
      ) : (
        <ul className="divide-y divide-line">
          {docs.data.map((d) => (
            <li key={d.id} className="px-4 py-2.5">
              {d.url ? (
                <a
                  href={d.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="line-clamp-2 text-[13px] leading-snug text-fg hover:text-accent hover:underline"
                >
                  {d.title}
                  <ExternalLink className="ml-1 inline size-3 text-muted" />
                </a>
              ) : (
                <p className="line-clamp-2 text-[13px] leading-snug text-fg">{d.title}</p>
              )}
              <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
                <DocTypeBadge type={d.doc_type} />
                {d.ticker && <span className="font-mono">{d.ticker}</span>}
                <span>{fmtDate(d.published_at ?? d.created_at)}</span>
                <span className="ml-auto">{t('docs.chunks', { n: d.chunks })}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
