import { useId, useState, type FormEvent, type Ref } from 'react'
import { Link, useNavigate } from 'react-router'
import { Briefcase, Check, Cpu, Play, Sparkles } from 'lucide-react'
import type { AnalystKey } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Field, Input, Switch } from '@/components/ui/Controls'
import { useCreateRun, useLlmSettings, usePortfolio } from '@/hooks/api'
import { useT } from '@/i18n/I18nProvider'
import { ANALYST_KEYS, providerShort } from '@/lib/constants'
import { cn } from '@/lib/cn'
import { toISODate } from '@/lib/format'

const QUICK_PICKS = [
  { ticker: '600519', name: 'quick.600519' },
  { ticker: '000001.SZ', name: 'quick.000001' },
  { ticker: '300750', name: 'quick.300750' },
] as const

/** Nudge to enter holdings when the account is empty, so decisions account for the real book. */
function HoldingsHint() {
  const t = useT()
  const { data } = usePortfolio()
  if (!data || data.positions.length > 0) return null
  return (
    <Link
      to="/portfolio"
      className="group flex gap-2 rounded-lg border border-warn/30 bg-warn/[0.06] px-3 py-2 text-xs leading-relaxed text-fg-2 hover:border-warn/60"
    >
      <Briefcase className="mt-0.5 size-3.5 shrink-0 text-warn" aria-hidden />
      <span>
        {t('runForm.noHoldings')}{' '}
        <span className="whitespace-nowrap text-accent group-hover:underline">{t('runForm.addHoldings')}</span>
      </span>
    </Link>
  )
}

/** "Model: Claude · quick / deep" with a link to Settings; hidden until the settings load. */
function ModelLine() {
  const t = useT()
  const { data } = useLlmSettings()
  if (!data) return null
  const keySet = data.keys[data.provider]?.set ?? false
  return (
    // Inline text (not flex chunks) so long custom model ids wrap naturally.
    <Link to="/settings" className="group block text-xs leading-relaxed text-muted hover:text-fg">
      <Cpu className="mr-1 inline size-3.5 align-[-3px]" aria-hidden />
      {t('runForm.model')}: <span className="font-medium text-fg-2">{providerShort(data.provider)}</span>{' '}
      <span className="font-mono text-fg-2">
        · {data.quick_model} / {data.deep_model}
      </span>
      {!keySet && <span className="text-warn"> · {t('runForm.noKey')}</span>}{' '}
      <span className="whitespace-nowrap text-accent group-hover:underline">{t('runForm.modelChange')} →</span>
    </Link>
  )
}

interface RunFormProps {
  ticker: string
  onTickerChange: (v: string) => void
  tickerRef?: Ref<HTMLInputElement>
}

/** "New analysis": start a multi-agent run, then jump to its live page. */
export function RunForm({ ticker, onTickerChange, tickerRef }: RunFormProps) {
  const t = useT()
  const ids = { ticker: useId(), date: useId(), auto: useId() }
  const [date, setDate] = useState('')
  const [analysts, setAnalysts] = useState<AnalystKey[]>([...ANALYST_KEYS])
  const [autoApprove, setAutoApprove] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const create = useCreateRun()
  const navigate = useNavigate()

  const tickerError = submitted && !ticker.trim() ? t('runForm.tickerRequired') : null
  const analystError = analysts.length === 0 ? t('runForm.analystsRequired') : null

  // Keep the canonical analyst order whatever the click order.
  const toggle = (key: AnalystKey) =>
    setAnalysts((cur) =>
      cur.includes(key) ? cur.filter((k) => k !== key) : ANALYST_KEYS.filter((k) => k === key || cur.includes(k)),
    )

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    setSubmitted(true)
    if (!ticker.trim() || analysts.length === 0) return
    create.mutate(
      { ticker: ticker.trim(), trade_date: date || null, analysts, auto_approve: autoApprove },
      { onSuccess: (run) => navigate(`/runs/${run.id}`) },
    )
  }

  return (
    <Card>
      <CardHeader title={t('runForm.title')} icon={<Sparkles />} subtitle={t('runForm.subtitle')} />
      <CardBody>
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
            <Field label={t('runForm.ticker')} htmlFor={ids.ticker} error={tickerError} hint="600519 / 000001.SZ / 300750">
              <Input
                id={ids.ticker}
                ref={tickerRef}
                value={ticker}
                onChange={(e) => onTickerChange(e.target.value)}
                placeholder={t('runForm.tickerPlaceholder')}
                autoComplete="off"
                spellCheck={false}
                className="font-mono"
              />
            </Field>
            <Field label={t('runForm.date')} htmlFor={ids.date} hint={date ? undefined : t('runForm.dateHint')}>
              <Input
                id={ids.date}
                type="date"
                value={date}
                max={toISODate(new Date())}
                onChange={(e) => setDate(e.target.value)}
              />
            </Field>
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-muted">{t('runForm.quickPick')}</span>
            {QUICK_PICKS.map((q) => (
              <button
                key={q.ticker}
                type="button"
                onClick={() => onTickerChange(q.ticker)}
                className="rounded-md border border-line px-2 py-0.5 text-xs text-fg-2 hover:border-accent hover:text-accent"
              >
                <span className="font-mono">{q.ticker}</span> {t(q.name)}
              </button>
            ))}
          </div>

          <fieldset>
            <legend className="mb-1.5 text-xs font-medium text-fg-2">{t('runForm.analysts')}</legend>
            <div className="flex flex-wrap gap-2">
              {ANALYST_KEYS.map((key) => {
                const on = analysts.includes(key)
                return (
                  <button
                    key={key}
                    type="button"
                    title={`${key}: ${t(`analyst.${key}.hint`)}`}
                    aria-pressed={on}
                    onClick={() => toggle(key)}
                    className={cn(
                      'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm transition',
                      on
                        ? 'border-accent bg-accent/10 text-accent'
                        : 'border-line text-muted hover:border-line-strong hover:text-fg',
                    )}
                  >
                    {on && <Check className="size-3.5" />}
                    {t(`analyst.${key}`)}
                  </button>
                )
              })}
            </div>
            {analystError && <p className="mt-1 text-xs text-up">{analystError}</p>}
          </fieldset>

          <Switch
            id={ids.auto}
            checked={autoApprove}
            onChange={setAutoApprove}
            label={t('runForm.autoApprove')}
            description={t('runForm.autoApproveDesc')}
          />

          <HoldingsHint />
          <ModelLine />

          <Button
            type="submit"
            variant="primary"
            className="w-full justify-center"
            loading={create.isPending}
            icon={<Play className="size-4" />}
            disabled={analysts.length === 0}
          >
            {t('runForm.submit')}
          </Button>
        </form>
      </CardBody>
    </Card>
  )
}
