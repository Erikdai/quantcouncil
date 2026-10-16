import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router'
import { ArrowDownToLine, BookOpenCheck, ExternalLink, Loader2, Search, X } from 'lucide-react'
import { deepResearch, researchActive, type ResearchEvidence, type ResearchFinding } from '@/api/deepResearch'
import { downloadFile } from '@/api/client'
import { PageHeader } from '@/components/layout/PageHeader'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Field, Input } from '@/components/ui/Controls'
import { EmptyState, ErrorState, SkeletonRows } from '@/components/ui/Feedback'
import { Modal } from '@/components/ui/Modal'
import { useI18n } from '@/i18n/I18nProvider'
import { useLlmSettings } from '@/hooks/api'
import { toISODate } from '@/lib/format'
import { cn } from '@/lib/cn'
import { toast } from '@/lib/toast'

export default function DeepResearchPage() {
  const { t, tx, lang } = useI18n()
  const { id } = useParams()
  const navigate = useNavigate()
  const client = useQueryClient()
  const [ticker, setTicker] = useState('MSFT')
  const [question, setQuestion] = useState('')
  const [date, setDate] = useState('')
  const [source, setSource] = useState<ResearchEvidence | null>(null)
  const [quote, setQuote] = useState('')
  const settings = useLlmSettings()
  const hasKey = settings.data?.keys[settings.data.provider]?.set
  const history = useQuery({ queryKey: ['deep-research'], queryFn: ({ signal }) => deepResearch.list(signal), refetchInterval: 6000 })
  const job = useQuery({
    queryKey: ['deep-research', id], queryFn: ({ signal }) => deepResearch.get(id!, signal), enabled: Boolean(id),
    refetchInterval: (q) => researchActive(q.state.data?.status) ? 2500 : false,
  })
  const onCreated = (data: { id: string }) => {
    void client.invalidateQueries({ queryKey: ['deep-research'] })
    navigate(`/deep-research/${data.id}`)
  }
  const create = useMutation({ mutationFn: deepResearch.create, onSuccess: onCreated })
  const retry = useMutation({ mutationFn: deepResearch.retry, onSuccess: onCreated })
  const cancel = useMutation({ mutationFn: deepResearch.cancel, onSuccess: () => { void job.refetch(); void history.refetch() } })
  const current = job.data
  const report = current?.report
  const label = (value: string) => tx(`deep.${value}`, value)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!ticker.trim() || question.trim().length < 10) return
    create.mutate({ ticker, question, as_of: date || null, language: lang })
  }
  const showSource = (sourceId: string, exactQuote = '') => {
    setSource(current?.sources.find((s) => s.id === sourceId) ?? null)
    setQuote(exactQuote)
  }
  const finding = (item: ResearchFinding, index: number) => (
    <div key={index} className="border-b border-line py-4 last:border-0">
      <span className={cn('mb-2 inline-block rounded px-1.5 py-0.5 text-[11px]', item.kind === 'fact' ? 'bg-info/10 text-info' : 'bg-warn/10 text-warn')}>{label(item.kind)}</span>
      <p className="text-sm leading-7 text-fg-2">{item.text}</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {item.citations.map((cite, i) => {
          const number = current?.sources.findIndex((s) => s.id === cite.source_id) ?? -1
          return <button key={i} disabled={number < 0} className="rounded border border-line px-2 py-1 text-xs text-accent hover:border-accent disabled:text-warn" onClick={() => showSource(cite.source_id, cite.quote)}>
            {number < 0 ? t('deep.referenceMissing') : `${t('deep.evidence')} ${number + 1}`}
          </button>
        })}
      </div>
    </div>
  )
  return (
    <>
      <PageHeader title={t('deep.title')} description={t('deep.description')} />
      <div className="grid items-start gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
        <aside className="space-y-5">
          <Card>
            <CardHeader title={t('deep.new')} icon={<Search />} />
            <CardBody>
              <form onSubmit={submit} className="space-y-4">
                <Field label={t('deep.ticker')} htmlFor="research-ticker" hint={t('deep.scope')}>
                  <Input id="research-ticker" value={ticker} onChange={(e) => setTicker(e.target.value)} required maxLength={12} />
                </Field>
                <Field label={t('deep.question')} htmlFor="research-question">
                  <textarea id="research-question" className="min-h-32 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm leading-6 text-fg outline-none focus:border-accent" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder={t('deep.placeholder')} required minLength={10} maxLength={1200} />
                </Field>
                <button type="button" onClick={() => { setTicker('MSFT'); setQuestion(t('deep.exampleQuestion')) }} className="text-left text-xs leading-5 text-accent hover:underline">{t('deep.example')}</button>
                <Field label={t('deep.asOf')} htmlFor="research-asof" hint={t('deep.asOfHint')}>
                  <Input id="research-asof" type="date" max={toISODate(new Date())} value={date} onChange={(e) => setDate(e.target.value)} />
                </Field>
                {settings.data && !hasKey && <Link className="block text-xs text-warn underline" to="/settings">{t('deep.needKey')}</Link>}
                <Button type="submit" variant="primary" loading={create.isPending} disabled={question.trim().length < 10 || (settings.isSuccess && !hasKey)} className="w-full justify-center" icon={<BookOpenCheck className="size-4" />}>{t('deep.start')}</Button>
                {create.isError && <p role="alert" className="text-xs text-up">{create.error.message}</p>}
                <p className="text-[11px] leading-5 text-muted">{t('deep.budget')}</p>
              </form>
            </CardBody>
          </Card>
          <Card>
            <CardHeader title={t('deep.history')} />
            <div className="max-h-96 overflow-auto">
              {history.isPending ? <SkeletonRows rows={3} className="p-4" /> : history.isError ? <ErrorState error={history.error} onRetry={() => void history.refetch()} /> : history.data.length === 0 ? <p className="p-4 text-xs text-muted">{t('deep.noHistory')}</p> : history.data.map((item) => (
                <Link key={item.id} to={`/deep-research/${item.id}`} className={cn('block border-b border-line px-4 py-3 last:border-0 hover:bg-surface-2', id === item.id && 'bg-accent/5')}>
                  <div className="mb-1 flex items-center justify-between text-xs"><strong>{item.ticker}</strong><span className="text-muted">{label(item.status)}</span></div>
                  <p className="line-clamp-2 text-xs leading-5 text-fg-2">{item.question}</p>
                  <p className="mt-1 text-[11px] text-muted">{item.as_of}</p>
                </Link>
              ))}
            </div>
          </Card>
        </aside>
        <main className="min-w-0 space-y-5">
          {!id ? <Card><EmptyState icon={<BookOpenCheck />} title={t('deep.emptyTitle')} description={t('deep.emptyDescription')} /></Card> : job.isPending ? <SkeletonRows rows={8} /> : job.isError ? <ErrorState error={job.error} onRetry={() => void job.refetch()} /> : current && <>
            <Card>
              <CardBody>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span className="text-xs font-medium text-accent">{current.ticker} · {current.as_of}</span>
                  <div className="flex gap-2">
                    {researchActive(current.status) ? <Button size="sm" onClick={() => cancel.mutate(current.id)} loading={cancel.isPending} icon={<X className="size-3.5" />}>{t('deep.cancel')}</Button> : <Button size="sm" onClick={() => retry.mutate(current.id)} loading={retry.isPending}>{t('deep.retry')}</Button>}
                    {report && <Button size="sm" icon={<ArrowDownToLine className="size-3.5" />} onClick={() => void downloadFile(`/deep-research/${current.id}/report.md`).catch((e: Error) => toast.error(e.message))}>{t('deep.export')}</Button>}
                  </div>
                </div>
                <h2 className="mt-3 text-xl leading-8 font-semibold text-fg">{current.question}</h2>
                <div role="status" className="mt-3 flex items-center gap-2 text-xs text-muted">
                  {researchActive(current.status) && <Loader2 className="size-3.5 animate-spin" />}
                  <span>{label(current.stage)}</span><span>· {current.model.provider} / {current.model.deep_model}</span>
                </div>
                {current.error && <p role="alert" className="mt-3 rounded-lg bg-up/5 p-3 text-sm text-up">{current.error}</p>}
                {(cancel.isError || retry.isError) && <p role="alert" className="mt-2 text-xs text-up">{cancel.error?.message ?? retry.error?.message}</p>}
                {current.warnings.length > 0 && <p className="mt-3 text-xs leading-5 text-warn">{t('deep.missing')}: {current.warnings.join('; ')}</p>}
              </CardBody>
            </Card>
            {current.plan && !report && <Card><CardHeader title={t('deep.plan')} /><CardBody><ul className="space-y-2 text-sm leading-6 text-fg-2">{current.plan.subquestions.map((q, i) => <li key={i}>{i + 1}. {q}</li>)}</ul></CardBody></Card>}
            {report && <article className="rounded-xl border border-line bg-surface px-5 py-5 sm:px-8">
              <p className="mb-3 text-xs text-muted">{t('deep.verdict')}: <strong className="text-fg">{label(report.verdict)}</strong></p>
              <h2 className="text-xl leading-8 font-semibold">{report.title}</h2>
              <p className="mt-2 text-xs text-muted">{t('deep.amountUnit')}</p>
              {finding(report.answer, -1)}
              <h3 className="mt-6 text-base font-semibold">{t('deep.findings')}</h3>{report.findings.map(finding)}
              <h3 className="mt-6 text-base font-semibold">{t('deep.counterarguments')}</h3>{report.counterarguments.map(finding)}
              <h3 className="mt-6 text-base font-semibold">{t('deep.unknowns')}</h3><ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-7 text-fg-2">{report.unknowns.map((line, i) => <li key={i}>{line}</li>)}</ul>
              <h3 className="mt-6 text-base font-semibold">{t('deep.change')}</h3><ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-7 text-fg-2">{report.what_would_change.map((line, i) => <li key={i}>{line}</li>)}</ul>
              <div className={cn('mt-6 rounded-lg border p-3 text-xs leading-6', current.verification?.passed ? 'border-line text-muted' : 'border-warn text-warn')}>
                <strong>{current.verification?.passed ? t('deep.verified') : t('deep.needs_review')}</strong><p>{t('deep.verificationScope')}</p>
                {current.verification?.semantic_review && <p>{t('deep.semanticScope')}</p>}
                {Boolean(current.verification?.errors.length) && <details><summary className="cursor-pointer">{t('deep.checkDetails')}</summary>{current.verification?.errors.map((error, i) => <p key={i}>{error}</p>)}</details>}
              </div>
            </article>}
            <Card>
              <CardHeader title={t('deep.evidence')} subtitle={t('deep.evidenceHint')} />
              <CardBody>
                <div className="flex flex-wrap gap-2">{current.manifest.map((file) => <a key={file.url} href={file.url} target="_blank" rel="noopener noreferrer" className="rounded border border-line px-2 py-1 text-xs text-accent">{file.form} · {file.period} <ExternalLink className="ml-1 inline size-3" /></a>)}</div>
                <div className="mt-3 max-h-80 divide-y divide-line overflow-auto">{current.sources.map((item, i) => <button key={item.id} onClick={() => { setSource(item); setQuote('') }} className="block w-full py-2 text-left text-xs leading-6 text-fg-2 hover:text-accent">[{i + 1}] {item.title}<span className="ml-2 text-muted">{item.filed}</span></button>)}</div>
                {!current.sources.length && <p className="text-xs text-muted">{t('deep.noEvidence')}</p>}
              </CardBody>
            </Card>
            <details className="rounded-xl border border-line bg-surface p-4"><summary className="cursor-pointer text-xs text-muted">{t('deep.activity')}</summary><ol className="mt-3 max-h-72 space-y-2 overflow-auto">{current.events.map((event, i) => <li key={i} className="text-xs leading-5 text-muted"><time>{new Date(event.at).toLocaleTimeString()}</time> {event.message}</li>)}</ol></details>
          </>}
        </main>
      </div>
      <Modal open={Boolean(source)} onClose={() => setSource(null)} title={t('deep.sourceTitle')}>
        {source && <div className="max-h-[65dvh] space-y-3 overflow-auto break-words">
          <p className="font-medium">{source.title}</p><a className="text-xs text-accent underline" href={source.url} target="_blank" rel="noopener noreferrer">{t('deep.original')} <ExternalLink className="inline size-3" /></a>
          <p className="text-xs text-muted">{t('deep.filed')}: {source.filed}</p>
          {quote && <blockquote className="border-l-2 border-accent bg-accent/5 p-3 text-xs leading-6">{quote}</blockquote>}
          <p className="whitespace-pre-wrap text-xs leading-6">{source.content}</p>
          {source.inputs.map((input) => <button key={input} className="mr-2 text-xs text-accent underline" onClick={() => showSource(input)}>{t('deep.input')}: {current?.sources.find((s) => s.id === input)?.title ?? input}</button>)}
          {source.sha256 && <p className="text-[10px] text-muted">SHA-256: {source.sha256}</p>}
        </div>}
      </Modal>
    </>
  )
}
