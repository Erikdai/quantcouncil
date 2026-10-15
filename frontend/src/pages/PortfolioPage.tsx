import { useId, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { Briefcase, ListOrdered, RotateCcw, ShieldAlert } from 'lucide-react'
import type { AccountOut, OrderOut, PositionOut } from '@/api/types'
import { SideBadge } from '@/components/common/Badges'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardHeader } from '@/components/ui/Card'
import { Field, Input } from '@/components/ui/Controls'
import { EmptyState, ErrorState, Skeleton, SkeletonRows } from '@/components/ui/Feedback'
import { Modal } from '@/components/ui/Modal'
import { useOrders, usePortfolio, useResetPortfolio } from '@/hooks/api'
import { useI18n, useT } from '@/i18n/I18nProvider'
import { cn } from '@/lib/cn'
import {
  changeClass,
  fmtCNY,
  fmtCNYCompact,
  fmtDateTime,
  fmtPct,
  fmtPrice,
  fmtShares,
  fmtSignedCNY,
} from '@/lib/format'
import { toast } from '@/lib/toast'

const MIN_INITIAL_CASH = 10_000

function Kpi({ label, value, sub, valueClass }: { label: string; value: ReactNode; sub?: ReactNode; valueClass?: string }) {
  return (
    <Card className="p-3 sm:p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className={cn('mt-1.5 truncate font-mono text-base font-semibold text-fg tabular-nums sm:text-xl', valueClass)}>
        {value}
      </p>
      {sub && <p className="mt-1 truncate text-xs text-muted">{sub}</p>}
    </Card>
  )
}

function KpiTiles({ a }: { a: AccountOut }) {
  const t = useT()
  const exposure = a.equity > 0 ? a.market_value / a.equity : 0
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      <Kpi label={t('kpi.equity')} value={fmtCNY(a.equity)} sub={t('kpi.initial', { v: fmtCNYCompact(a.initial_cash) })} />
      <Kpi
        label={t('kpi.cash')}
        value={fmtCNY(a.cash)}
        sub={t('kpi.cashShare', { v: fmtPct(a.equity > 0 ? a.cash / a.equity : 0, { digits: 1 }) })}
      />
      <Kpi
        label={t('kpi.marketValue')}
        value={fmtCNY(a.market_value)}
        sub={t('kpi.exposure', { v: fmtPct(exposure, { digits: 1 }) })}
      />
      <Kpi
        label={t('kpi.pnl')}
        value={fmtSignedCNY(a.pnl)}
        valueClass={changeClass(a.pnl)}
        sub={<span className={changeClass(a.pnl_pct)}>{fmtPct(a.pnl_pct, { sign: true })}</span>}
      />
      <Kpi
        label={t('kpi.drawdown')}
        value={fmtPct(a.drawdown_pct > 0 ? -a.drawdown_pct : 0)}
        valueClass={a.drawdown_pct > 0 ? 'text-down' : undefined}
        sub={t('kpi.peak', { v: fmtCNYCompact(a.peak_equity) })}
      />
    </div>
  )
}

/** Stacked bar: each position's weight of equity, plus cash. */
function AllocationBar({ a, positions }: { a: AccountOut; positions: PositionOut[] }) {
  const t = useT()
  if (a.equity <= 0) return null
  const segs = positions
    .map((p) => ({ key: p.ticker, label: p.name ?? p.ticker, w: p.weight ?? (p.market_value ?? 0) / a.equity }))
    .filter((s) => s.w > 0)
    .sort((x, y) => y.w - x.w)
  const cashW = Math.max(0, a.cash / a.equity)
  const cashLabel = t('pos.cash')
  return (
    <div>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-surface-3" aria-label={t('pos.allocation')}>
        {segs.map((s, i) => (
          <div
            key={s.key}
            title={`${s.label} ${fmtPct(s.w, { digits: 1 })}`}
            className="h-full border-r border-surface bg-accent"
            style={{ width: `${s.w * 100}%`, opacity: Math.max(0.35, 1 - i * 0.12) }}
          />
        ))}
        <div
          title={`${cashLabel} ${fmtPct(cashW, { digits: 1 })}`}
          className="h-full bg-line-strong/60"
          style={{ width: `${cashW * 100}%` }}
        />
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
        {segs.slice(0, 6).map((s, i) => (
          <span key={s.key} className="inline-flex items-center gap-1">
            <span className="size-2 rounded-sm bg-accent" style={{ opacity: Math.max(0.35, 1 - i * 0.12) }} />
            {s.label} {fmtPct(s.w, { digits: 1 })}
          </span>
        ))}
        <span className="inline-flex items-center gap-1">
          <span className="size-2 rounded-sm bg-line-strong/60" /> {cashLabel} {fmtPct(cashW, { digits: 1 })}
        </span>
      </div>
    </div>
  )
}

function PositionsTable({ positions }: { positions: PositionOut[] }) {
  const t = useT()
  if (positions.length === 0)
    return <EmptyState icon={<Briefcase />} title={t('pos.emptyTitle')} description={t('pos.emptyDesc')} />
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead>
          <tr className="border-b border-line text-right text-xs text-muted [&>th]:px-3 [&>th]:py-2 [&>th]:font-medium">
            <th className="!pl-4 text-left">{t('pos.colStock')}</th>
            <th>{t('pos.colQty')}</th>
            <th title={t('pos.colAvailableTitle')}>{t('pos.colAvailable')}</th>
            <th>{t('pos.colCost')}</th>
            <th>{t('pos.colPrice')}</th>
            <th>{t('pos.colValue')}</th>
            <th>{t('pos.colPnl')}</th>
            <th className="!pr-4">{t('pos.colWeight')}</th>
          </tr>
        </thead>
        <tbody className="font-mono text-[13px]">
          {positions.map((p) => {
            const pct = p.last_price != null && p.avg_cost > 0 ? p.last_price / p.avg_cost - 1 : null
            const locked = p.quantity - p.available_quantity
            return (
              <tr
                key={p.ticker}
                className="border-b border-line/70 text-right last:border-0 hover:bg-surface-2 [&>td]:px-3 [&>td]:py-2.5"
              >
                <td className="!pl-4 text-left font-sans">
                  <span className="font-mono font-medium text-fg">{p.ticker}</span>
                  <span className="ml-2 text-xs text-muted">{p.name ?? ''}</span>
                </td>
                <td>{fmtShares(p.quantity)}</td>
                <td>
                  {fmtShares(p.available_quantity)}
                  {locked > 0 && (
                    <span className="ml-1 font-sans text-[11px] text-warn" title={t('pos.lockedTitle')}>
                      {t('pos.locked', { n: fmtShares(locked) })}
                    </span>
                  )}
                </td>
                <td>{fmtPrice(p.avg_cost)}</td>
                <td className={changeClass(pct)}>{fmtPrice(p.last_price)}</td>
                <td>{fmtCNY(p.market_value)}</td>
                <td className={changeClass(p.unrealized_pnl)}>
                  {fmtSignedCNY(p.unrealized_pnl)}
                  {pct !== null && <span className="block text-[11px]">{fmtPct(pct, { sign: true })}</span>}
                </td>
                <td className="!pr-4">{fmtPct(p.weight, { digits: 1 })}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

const ORDER_TONE: Record<string, 'info' | 'warn'> = { filled: 'info', rejected: 'warn' }

function OrdersTable({ orders }: { orders: OrderOut[] }) {
  const { t, tx } = useI18n()
  if (orders.length === 0) return <EmptyState icon={<ListOrdered />} title={t('orders.empty')} />
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs text-muted [&>th]:px-3 [&>th]:py-2 [&>th]:font-medium">
            <th className="!pl-4">{t('orders.colTime')}</th>
            <th>{t('orders.colStock')}</th>
            <th>{t('orders.colSide')}</th>
            <th className="text-right">{t('orders.colQty')}</th>
            <th className="text-right">{t('orders.colPrice')}</th>
            <th className="text-right">{t('orders.colFees')}</th>
            <th>{t('orders.colStatus')}</th>
            <th>{t('orders.colSource')}</th>
            <th className="!pr-4">{t('orders.colComment')}</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.id} className="border-b border-line/70 last:border-0 hover:bg-surface-2 [&>td]:px-3 [&>td]:py-2.5">
              <td className="!pl-4 text-xs whitespace-nowrap text-muted">{fmtDateTime(o.created_at)}</td>
              <td className="font-mono text-[13px] font-medium text-fg">{o.ticker}</td>
              <td>
                <SideBadge side={o.side} />
              </td>
              <td className="text-right font-mono text-[13px]">{fmtShares(o.quantity)}</td>
              <td className="text-right font-mono text-[13px]">{fmtPrice(o.price)}</td>
              <td className="text-right font-mono text-[13px] text-muted">{fmtCNY(o.fees)}</td>
              <td>
                <Badge tone={ORDER_TONE[o.status] ?? 'muted'}>{tx(`orderStatus.${o.status}`, o.status)}</Badge>
              </td>
              <td className="text-xs">
                {o.run_id ? (
                  <Link to={`/runs/${o.run_id}`} className="text-accent hover:underline">
                    {t('orders.viewRun')}
                  </Link>
                ) : (
                  <span className="text-muted">{t('orders.manual')}</span>
                )}
              </td>
              <td className="!pr-4 max-w-56 truncate text-xs text-muted" title={o.comment ?? undefined}>
                {o.comment ?? '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ResetDialog({ open, onClose, defaultCash }: { open: boolean; onClose: () => void; defaultCash: number }) {
  const t = useT()
  const id = useId()
  const reset = useResetPortfolio()
  const [cash, setCash] = useState(String(defaultCash))
  const n = Number(cash)
  const invalid = !Number.isFinite(n) || n < MIN_INITIAL_CASH

  const confirm = () => {
    if (invalid) return
    reset.mutate(n, {
      onSuccess: () => {
        toast.success(t('reset.done'), t('reset.doneDesc', { v: fmtCNY(n, 0) }))
        onClose()
      },
    })
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('reset.title')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={reset.isPending}>
            {t('common.cancel')}
          </Button>
          <Button variant="danger" onClick={confirm} loading={reset.isPending} disabled={invalid}>
            {t('reset.confirm')}
          </Button>
        </>
      }
    >
      <p className="mb-4 flex gap-2 rounded-lg bg-warn/10 p-3 text-xs text-fg-2">
        <ShieldAlert className="size-4 shrink-0 text-warn" />
        {t('reset.warning')}
      </p>
      <Field label={t('reset.cash')} htmlFor={id} error={invalid ? t('reset.min') : undefined}>
        <Input
          id={id}
          type="number"
          inputMode="decimal"
          min={MIN_INITIAL_CASH}
          step={10_000}
          value={cash}
          onChange={(e) => setCash(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && confirm()}
          className="font-mono"
        />
      </Field>
      <div className="mt-2 flex gap-1.5">
        {[100_000, 1_000_000, 10_000_000].map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => setCash(String(v))}
            className="rounded-md border border-line px-2 py-0.5 text-xs text-fg-2 hover:border-accent hover:text-accent"
          >
            {fmtCNYCompact(v, 0)}
          </button>
        ))}
      </div>
    </Modal>
  )
}

export default function PortfolioPage() {
  const t = useT()
  const pf = usePortfolio()
  const orders = useOrders(50)
  const [resetOpen, setResetOpen] = useState(false)

  return (
    <>
      <PageHeader
        title={t('pf.title')}
        description={t('pf.desc')}
        actions={
          <>
            {pf.data &&
              (pf.data.ledger_verified ? (
                <Badge tone="ok" title={t('pf.ledgerOkTitle')}>
                  {t('pf.ledgerOk')}
                </Badge>
              ) : (
                <Badge tone="up" title={t('pf.ledgerBadTitle')}>
                  {t('pf.ledgerBad')}
                </Badge>
              ))}
            <Button icon={<RotateCcw className="size-4" />} onClick={() => setResetOpen(true)} disabled={!pf.data}>
              {t('pf.reset')}
            </Button>
          </>
        }
      />

      {pf.isPending ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-[92px] rounded-xl" />
          ))}
        </div>
      ) : pf.isError ? (
        <Card>
          <ErrorState error={pf.error} onRetry={() => void pf.refetch()} />
        </Card>
      ) : (
        <div className="space-y-5">
          <KpiTiles a={pf.data.account} />
          <Card>
            <CardHeader
              title={t('pos.title')}
              icon={<Briefcase />}
              subtitle={t('pos.count', { n: pf.data.positions.length })}
            />
            {pf.data.positions.length > 0 && (
              <div className="border-b border-line px-4 py-3">
                <AllocationBar a={pf.data.account} positions={pf.data.positions} />
              </div>
            )}
            <PositionsTable positions={pf.data.positions} />
          </Card>
        </div>
      )}

      <Card className="mt-5">
        <CardHeader title={t('orders.title')} icon={<ListOrdered />} subtitle={t('orders.subtitle')} />
        {orders.isPending ? (
          <SkeletonRows rows={4} className="p-4" />
        ) : orders.isError ? (
          <ErrorState error={orders.error} onRetry={() => void orders.refetch()} />
        ) : (
          <OrdersTable orders={orders.data} />
        )}
      </Card>

      {pf.data && (
        <ResetDialog
          key={String(resetOpen)}
          open={resetOpen}
          onClose={() => setResetOpen(false)}
          defaultCash={pf.data.account.initial_cash || 1_000_000}
        />
      )}
    </>
  )
}
