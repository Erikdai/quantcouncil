import { useState, type FormEvent } from 'react'
import { Check, Info, Pencil, Plus, Trash, Wallet, X } from 'lucide-react'
import type { PortfolioOut, PositionOut } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Field, Input } from '@/components/ui/Controls'
import { useRemoveHolding, useSetCash, useSetHolding } from '@/hooks/api'
import { useT, type TFunction } from '@/i18n/I18nProvider'
import { cn } from '@/lib/cn'
import { fmtCNY } from '@/lib/format'
import { toast } from '@/lib/toast'

const isWhole = (s: string) => /^\d+$/.test(s.trim())
const asNumber = (s: string) => (s.trim() === '' ? NaN : Number(s))

function quantityError(t: TFunction, v: string, allowZero: boolean): string | null {
  if (!isWhole(v) || (!allowZero && Number(v) === 0)) return allowZero ? t('holdings.errQty') : t('holdings.errAddQty')
  return null
}
const costError = (t: TFunction, v: string) => (!(asNumber(v) > 0) ? t('holdings.errCost') : null)

/** Add a holding the user already owns. */
function AddHolding() {
  const t = useT()
  const setHolding = useSetHolding()
  const [ticker, setTicker] = useState('')
  const [qty, setQty] = useState('')
  const [cost, setCost] = useState('')
  const [submitted, setSubmitted] = useState(false)

  const errors = {
    ticker: ticker.trim() ? null : t('holdings.errTicker'),
    qty: quantityError(t, qty, false),
    cost: costError(t, cost),
  }
  const invalid = Object.values(errors).some(Boolean)

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    setSubmitted(true)
    if (invalid) return
    setHolding.mutate(
      { ticker: ticker.trim(), quantity: Number(qty), avgCost: Number(cost) },
      {
        onSuccess: () => {
          toast.success(t('holdings.saved'), ticker.trim())
          setTicker('')
          setQty('')
          setCost('')
          setSubmitted(false)
        },
      },
    )
  }

  return (
    <form onSubmit={onSubmit} noValidate className="grid grid-cols-2 items-start gap-3 sm:grid-cols-[1fr_1fr_1fr_auto]">
      <Field label={t('holdings.ticker')} error={submitted ? errors.ticker : undefined}>
        <Input
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder="601318"
          className="font-mono"
          autoComplete="off"
          aria-label={t('holdings.ticker')}
        />
      </Field>
      <Field label={t('holdings.quantity')} error={submitted ? errors.qty : undefined}>
        <Input
          type="number"
          inputMode="numeric"
          min={1}
          step={100}
          value={qty}
          onChange={(e) => setQty(e.target.value)}
          placeholder="500"
          className="font-mono"
          aria-label={t('holdings.quantity')}
        />
      </Field>
      <Field label={t('holdings.avgCost')} error={submitted ? errors.cost : undefined}>
        <Input
          type="number"
          inputMode="decimal"
          min={0}
          step={0.01}
          value={cost}
          onChange={(e) => setCost(e.target.value)}
          placeholder="45.00"
          className="font-mono"
          aria-label={t('holdings.avgCost')}
        />
      </Field>
      <div className="flex items-end sm:pt-[22px]">
        <Button type="submit" variant="primary" icon={<Plus className="size-4" />} loading={setHolding.isPending}>
          {t('holdings.addBtn')}
        </Button>
      </div>
    </form>
  )
}

/** One editable holding row: quantity / average cost, save, two-step remove. */
function HoldingRow({ position }: { position: PositionOut }) {
  const t = useT()
  const setHolding = useSetHolding()
  const remove = useRemoveHolding()
  const [qty, setQty] = useState(String(position.quantity))
  const [cost, setCost] = useState(String(position.avg_cost))
  const [confirming, setConfirming] = useState(false)

  const qtyErr = quantityError(t, qty, true)
  const costErr = costError(t, cost)
  const changed = Number(qty) !== position.quantity || Number(cost) !== position.avg_cost
  const busy = setHolding.isPending || remove.isPending

  const onSave = () =>
    setHolding.mutate(
      { ticker: position.ticker, quantity: Number(qty), avgCost: Number(cost) },
      { onSuccess: () => toast.success(t('holdings.saved'), position.ticker) },
    )
  const onRemove = () => {
    if (!confirming) return setConfirming(true)
    remove.mutate(position.ticker, {
      onSuccess: () => toast.success(t('holdings.removed', { ticker: position.ticker })),
      onSettled: () => setConfirming(false),
    })
  }

  return (
    <li className="grid grid-cols-2 items-center gap-2 py-2.5 sm:grid-cols-[minmax(0,1.3fr)_1fr_1fr_13rem]">
      <div className="col-span-2 min-w-0 sm:col-span-1">
        <span className="font-mono text-[13px] font-medium text-fg">{position.ticker}</span>
        <span className="ml-2 text-xs text-muted">{position.name ?? ''}</span>
      </div>
      <Input
        type="number"
        inputMode="numeric"
        min={0}
        step={100}
        value={qty}
        onChange={(e) => setQty(e.target.value)}
        aria-label={`${position.ticker} ${t('holdings.quantity')}`}
        aria-invalid={!!qtyErr}
        title={qtyErr ?? undefined}
        className={cn('font-mono', qtyErr && 'border-up')}
      />
      <Input
        type="number"
        inputMode="decimal"
        min={0}
        step={0.01}
        value={cost}
        onChange={(e) => setCost(e.target.value)}
        aria-label={`${position.ticker} ${t('holdings.avgCost')}`}
        aria-invalid={!!costErr}
        title={costErr ?? undefined}
        className={cn('font-mono', costErr && 'border-up')}
      />
      <div className="col-span-2 flex justify-end gap-1.5 sm:col-span-1">
        <Button
          size="sm"
          variant={changed ? 'primary' : 'secondary'}
          icon={<Check className="size-3.5" />}
          disabled={!changed || !!qtyErr || !!costErr || busy}
          loading={setHolding.isPending}
          onClick={onSave}
        >
          {t('holdings.save')}
        </Button>
        <Button
          size="sm"
          variant={confirming ? 'danger' : 'ghost'}
          icon={<Trash className="size-3.5" />}
          disabled={busy && !remove.isPending}
          loading={remove.isPending}
          onClick={onRemove}
          onBlur={() => setConfirming(false)}
          className={cn(!confirming && 'text-muted hover:text-up')}
        >
          {confirming ? t('holdings.confirmRemove') : t('holdings.remove')}
        </Button>
      </div>
    </li>
  )
}

/** Set the account's cash (the capital base moves by the same amount). */
function CashRow({ cash }: { cash: number }) {
  const t = useT()
  const setCash = useSetCash()
  const [value, setValue] = useState(String(cash))
  const n = asNumber(value)
  const error = !(n >= 0) ? t('holdings.errCash') : null

  return (
    <div className="flex flex-wrap items-end gap-3">
      <Field label={t('holdings.cash')} hint={error ? undefined : t('holdings.cashHint')} error={error} className="min-w-48 flex-1">
        <Input
          type="number"
          inputMode="decimal"
          min={0}
          step={1000}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="font-mono"
          aria-label={t('holdings.cash')}
        />
      </Field>
      <Button
        icon={<Wallet className="size-4" />}
        loading={setCash.isPending}
        disabled={!!error || n === cash}
        onClick={() =>
          setCash.mutate(n, { onSuccess: () => toast.success(t('holdings.cashSaved'), fmtCNY(n)) })
        }
        className="mb-[22px]"
      >
        {t('holdings.setCash')}
      </Button>
    </div>
  )
}

/** Inline editor for the holdings and cash the user already has. */
export function HoldingsEditor({ portfolio, onClose }: { portfolio: PortfolioOut; onClose: () => void }) {
  const t = useT()
  const positions = portfolio.positions
  return (
    <Card className="border-accent/40 ring-4 ring-accent/10">
      <CardHeader
        title={t('holdings.title')}
        icon={<Pencil />}
        subtitle={t('holdings.subtitle')}
        actions={
          <Button size="sm" variant="ghost" icon={<X className="size-4" />} onClick={onClose}>
            {t('holdings.close')}
          </Button>
        }
      />
      <CardBody className="space-y-5">
        <p className="flex gap-2 rounded-lg bg-accent/[0.06] p-3 text-xs leading-relaxed text-fg-2">
          <Info className="mt-0.5 size-4 shrink-0 text-accent" />
          {t('holdings.hint')}
        </p>

        <section>
          <h3 className="mb-2 text-xs font-semibold text-fg-2">{t('holdings.add')}</h3>
          <AddHolding />
        </section>

        <section>
          {positions.length === 0 ? (
            <p className="text-sm text-muted">{t('holdings.empty')}</p>
          ) : (
            <>
              {/* Column labels; on phones each input keeps its own aria-label instead. */}
              <div className="hidden grid-cols-[minmax(0,1.3fr)_1fr_1fr_13rem] gap-2 pb-1.5 text-xs font-medium text-fg-2 sm:grid">
                <span>{t('holdings.ticker')}</span>
                <span>{t('holdings.quantity')}</span>
                <span>{t('holdings.avgCost')}</span>
                <span aria-hidden />
              </div>
              <ul className="divide-y divide-line border-y border-line">
              {positions.map((p) => (
                // Keyed by the saved values so a row resets after the server confirms an edit.
                <HoldingRow key={`${p.ticker}-${p.quantity}-${p.avg_cost}`} position={p} />
              ))}
              </ul>
            </>
          )}
        </section>

        <CashRow key={portfolio.account.cash} cash={portfolio.account.cash} />
      </CardBody>
    </Card>
  )
}
