import { ExternalLink } from 'lucide-react'
import type { Citation } from '@/api/types'
import { Badge } from '@/components/ui/Badge'
import { useI18n, useT } from '@/i18n/I18nProvider'
import { cn } from '@/lib/cn'
import { fmtDate, fmtScore } from '@/lib/format'

export function DocTypeBadge({ type }: { type: string }) {
  const { tx } = useI18n()
  const tone = type === 'announcement' ? 'accent' : type === 'research' ? 'info' : 'muted'
  return <Badge tone={tone}>{tx(`docType.${type}`, type)}</Badge>
}

/** One source document with its best-scoring passage and how many more passages it contributed. */
export interface SourceGroup {
  best: Citation
  passages: number
}

/**
 * Group retrieved passages by document, keeping first-seen order (the retrieval rank)
 * and each document's best-scoring passage, so one long report does not fill the list.
 */
export function groupByDocument(citations: Citation[]): SourceGroup[] {
  const groups = new Map<number, SourceGroup>()
  for (const c of citations) {
    const g = groups.get(c.document_id)
    if (!g) groups.set(c.document_id, { best: c, passages: 1 })
    else groups.set(c.document_id, { best: c.score > g.best.score ? c : g.best, passages: g.passages + 1 })
  }
  return [...groups.values()]
}

/** Numbered source card for a retrieved passage (optionally standing for a whole document). */
export function CitationCard({
  index,
  citation,
  maxScore,
  extraPassages = 0,
  snippet = 'full',
}: {
  index: number
  citation: Citation
  /** Normalises the score bar within one result set (scales differ by retrieval mode). */
  maxScore?: number
  /** Further passages of the same document, shown as "+N passages". */
  extraPassages?: number
  snippet?: 'full' | 'short' | 'none'
}) {
  const t = useT()
  const c = citation
  const rel = maxScore && maxScore > 0 ? Math.max(0, Math.min(1, c.score / maxScore)) : null
  const titleClass = 'line-clamp-2 text-[13px] leading-snug font-medium text-fg'
  return (
    <div className="flex gap-2.5 rounded-lg border border-line bg-surface p-2.5 transition hover:border-line-strong">
      <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded bg-accent/10 font-mono text-[11px] font-semibold text-accent">
        {index}
      </span>
      <div className="min-w-0 flex-1">
        {c.url ? (
          <a
            href={c.url}
            target="_blank"
            rel="noopener noreferrer"
            className={cn(titleClass, 'hover:text-accent hover:underline')}
          >
            {c.title}
            <ExternalLink className="ml-1 inline size-3 align-baseline text-muted" />
          </a>
        ) : (
          <span className={titleClass}>{c.title}</span>
        )}
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
          <DocTypeBadge type={c.doc_type} />
          {c.ticker && <span className="font-mono">{c.ticker}</span>}
          {c.published_at && <span>{fmtDate(c.published_at)}</span>}
          {extraPassages > 0 && (
            <span className="rounded bg-surface-2 px-1 text-fg-2">{t('chat.morePassages', { n: extraPassages })}</span>
          )}
          <span className="ml-auto inline-flex items-center gap-1.5 font-mono" title={t('search.score')}>
            {rel !== null && (
              <span className="inline-block h-1 w-10 overflow-hidden rounded-full bg-surface-3">
                <span className="block h-full rounded-full bg-accent" style={{ width: `${rel * 100}%` }} />
              </span>
            )}
            {fmtScore(c.score)}
          </span>
        </div>
        {snippet !== 'none' && c.snippet && (
          <p
            className={cn(
              'mt-1.5 text-xs leading-relaxed text-fg-2',
              snippet === 'short' ? 'line-clamp-2' : 'line-clamp-3',
            )}
          >
            {c.snippet}
          </p>
        )}
      </div>
    </div>
  )
}
