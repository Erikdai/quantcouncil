import { useState, type FormEvent } from 'react'
import { useQueries } from '@tanstack/react-query'
import { Columns2, Search } from 'lucide-react'
import { api } from '@/api/client'
import type { SearchMode, SearchOut } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { Input, Segmented } from '@/components/ui/Controls'
import { EmptyState, ErrorState, SkeletonRows } from '@/components/ui/Feedback'
import { qk, useSearch } from '@/hooks/api'
import { useT } from '@/i18n/I18nProvider'
import { SEARCH_MODES } from '@/lib/constants'
import { cn } from '@/lib/cn'
import { fmtScore } from '@/lib/format'
import { CitationCard } from './CitationCard'

const K = 8

function maxScore(out: SearchOut | undefined): number {
  return out?.results.reduce((m, r) => Math.max(m, r.score), 0) ?? 0
}

function SingleMode({ q, ticker, mode }: { q: string; ticker: string | null; mode: SearchMode }) {
  const t = useT()
  const { data, isFetching, isError, error, refetch } = useSearch(q, ticker, mode, K)
  if (isFetching && !data) return <SkeletonRows rows={4} className="p-4" />
  if (isError) return <ErrorState error={error} title={t('search.failed')} onRetry={() => void refetch()} />
  if (!data) return null
  if (data.results.length === 0)
    return <EmptyState title={t('search.noResults')} description={t('search.noResultsDesc')} />
  const max = maxScore(data)
  return (
    <div className={cn('space-y-1.5 p-3', isFetching && 'opacity-60')}>
      {data.results.map((c, i) => (
        <CitationCard key={`${c.chunk_id}-${i}`} index={i + 1} citation={c} maxScore={max} />
      ))}
    </div>
  )
}

/** All four retrieval modes side by side: a quick retrieval ablation. */
function CompareModes({ q, ticker }: { q: string; ticker: string | null }) {
  const t = useT()
  const results = useQueries({
    queries: SEARCH_MODES.map((mode) => ({
      queryKey: qk.search(q, ticker, mode, K),
      queryFn: ({ signal }: { signal: AbortSignal }) => api.search({ q, ticker, k: K, mode }, signal),
      staleTime: 60_000,
    })),
  })
  // Chunks returned by every mode are marked as consensus hits.
  const sets = results.map((r) => new Set(r.data?.results.map((c) => c.chunk_id) ?? []))
  const everyMode = (id: number) => results.every((r) => r.data) && sets.every((s) => s.has(id))

  return (
    <div className="grid gap-3 p-3 sm:grid-cols-2">
      {SEARCH_MODES.map((mode, mi) => {
        const r = results[mi]
        return (
          <div key={mode} className="min-w-0 rounded-lg border border-line">
            <div className="flex items-center justify-between border-b border-line px-2.5 py-1.5" title={t(`searchMode.${mode}.hint`)}>
              <span className="text-xs font-medium text-fg">{t(`searchMode.${mode}`)}</span>
              <span className="font-mono text-[10px] text-muted">{mode}</span>
            </div>
            {!r || r.isPending ? (
              <SkeletonRows rows={3} className="p-2.5 [&>div]:h-6" />
            ) : r.isError ? (
              <p className="p-2.5 text-xs text-up">{t('search.failed')}</p>
            ) : r.data.results.length === 0 ? (
              <p className="p-2.5 text-xs text-muted">{t('search.none')}</p>
            ) : (
              <ol className="divide-y divide-line/70">
                {r.data.results.map((c, i) => (
                  <li key={`${c.chunk_id}-${i}`} className="flex items-baseline gap-2 px-2.5 py-1.5 text-xs">
                    <span className="w-4 shrink-0 font-mono text-muted">{i + 1}</span>
                    <span
                      className={cn('min-w-0 flex-1 truncate', everyMode(c.chunk_id) ? 'font-medium text-accent' : 'text-fg-2')}
                      title={`${c.title}\n${c.snippet}`}
                    >
                      {c.title}
                    </span>
                    <span className="shrink-0 font-mono text-[10px] text-muted">{fmtScore(c.score, 3)}</span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        )
      })}
      <p className="text-[11px] text-muted sm:col-span-2">
        <span className="font-medium text-accent">{t('search.consensus')}</span>
        {t('search.consensusNote')}
      </p>
    </div>
  )
}

/** Retrieval playground over the RAG index, with a mode selector for ablation demos. */
export function SearchPanel({ ticker }: { ticker: string }) {
  const t = useT()
  const [input, setInput] = useState('')
  const [q, setQ] = useState('')
  const [mode, setMode] = useState<SearchMode>('hybrid')
  const [compare, setCompare] = useState(false)
  const scope = ticker.trim() || null

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    setQ(input.trim())
  }

  return (
    <div>
      <form onSubmit={onSubmit} className="space-y-2.5 border-b border-line px-4 py-3">
        <div className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={t('search.placeholder')}
            aria-label={t('search.aria')}
          />
          <Button type="submit" variant="primary" icon={<Search className="size-4" />} disabled={!input.trim()}>
            {t('search.submit')}
          </Button>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          {!compare ? (
            <Segmented
              options={SEARCH_MODES.map((m) => ({ value: m, label: t(`searchMode.${m}`), title: t(`searchMode.${m}.hint`) }))}
              value={mode}
              onChange={setMode}
            />
          ) : (
            <span className="text-xs text-muted">{t('search.compareAll', { k: K })}</span>
          )}
          <Button
            size="sm"
            variant={compare ? 'primary' : 'ghost'}
            icon={<Columns2 className="size-3.5" />}
            aria-pressed={compare}
            onClick={() => setCompare((c) => !c)}
          >
            {t('search.compare')}
          </Button>
        </div>
      </form>

      {!q ? (
        <EmptyState icon={<Search />} title={t('search.emptyTitle')} description={t('search.emptyDesc')} />
      ) : compare ? (
        <CompareModes q={q} ticker={scope} />
      ) : (
        <SingleMode q={q} ticker={scope} mode={mode} />
      )}
    </div>
  )
}
