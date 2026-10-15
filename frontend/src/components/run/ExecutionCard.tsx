import { Link } from 'react-router'
import { Receipt } from 'lucide-react'
import type { Execution } from '@/api/types'
import { SideBadge } from '@/components/common/Badges'
import { Badge } from '@/components/ui/Badge'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { useI18n } from '@/i18n/I18nProvider'
import { fmtCNY, fmtPrice, fmtShares } from '@/lib/format'

/** Paper-trading fill (or rejection) for the run's order. */
export function ExecutionCard({ execution }: { execution: Execution }) {
  const { t, tx } = useI18n()
  const fees = Object.entries(execution.fees ?? {})
  const totalFees = execution.fees?.total ?? fees.reduce((s, [, v]) => s + (typeof v === 'number' ? v : 0), 0)
  const filled = execution.status === 'filled'

  return (
    <Card>
      <CardHeader
        title={t('exec.title')}
        icon={<Receipt />}
        subtitle={<span className="font-mono">{execution.order_id}</span>}
        actions={
          <>
            <Badge tone={filled ? 'info' : 'warn'}>{filled ? t('exec.filled') : t('exec.notFilled')}</Badge>
            <Link to="/portfolio" className="text-xs text-accent hover:underline">
              {t('exec.viewAccount')}
            </Link>
          </>
        }
      />
      <CardBody className="space-y-3">
        {!filled && execution.reason && (
          <p className="rounded-lg border-l-4 border-warn bg-warn/[0.07] px-3 py-2 text-sm text-fg-2">{execution.reason}</p>
        )}
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-[11px] text-muted">{t('exec.side')}</dt>
            <dd className="mt-0.5">
              <SideBadge side={execution.side} />
            </dd>
          </div>
          <div>
            <dt className="text-[11px] text-muted">{t('exec.quantity')}</dt>
            <dd className="mt-0.5 font-mono">{t('common.shares', { n: fmtShares(execution.quantity) })}</dd>
          </div>
          <div>
            <dt className="text-[11px] text-muted">{t('exec.price')}</dt>
            <dd className="mt-0.5 font-mono">¥{fmtPrice(execution.price)}</dd>
          </div>
          <div>
            <dt className="text-[11px] text-muted">{t('exec.cashAfter')}</dt>
            <dd className="mt-0.5 font-mono">{fmtCNY(execution.cash_after)}</dd>
          </div>
        </dl>
        {fees.length > 0 && (
          <div className="rounded-lg bg-surface-2 px-3 py-2">
            <div className="mb-1 flex items-center justify-between text-xs">
              <span className="font-medium text-fg-2">{t('exec.fees')}</span>
              <span className="font-mono text-fg">{fmtCNY(totalFees)}</span>
            </div>
            <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
              {fees
                .filter(([k]) => k !== 'total')
                .map(([k, v]) => (
                  <li key={k}>
                    {tx(`fee.${k}`, k)} <span className="font-mono text-fg-2">{fmtCNY(v)}</span>
                  </li>
                ))}
            </ul>
          </div>
        )}
      </CardBody>
    </Card>
  )
}
