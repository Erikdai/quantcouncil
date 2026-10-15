import { useId, useState } from 'react'
import { Check, Pencil, UserCheck, X } from 'lucide-react'
import type { ApprovalAction, OrderProposal, RiskCheck } from '@/api/types'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Field, Input, inputClass } from '@/components/ui/Controls'
import { useApproveRun } from '@/hooks/api'
import { useT, type TFunction } from '@/i18n/I18nProvider'
import { cn } from '@/lib/cn'
import { LOT_SIZE } from '@/lib/constants'
import { fmtShares } from '@/lib/format'
import { toast } from '@/lib/toast'
import { OrderTable } from './RiskCheckPanel'

/** Buys must be whole board lots; sells may include an odd lot (limited by T+1 on the server). */
function validateQty(t: TFunction, qty: string, side: OrderProposal['side'] | undefined): string | null {
  if (!qty.trim()) return t('approval.errRequired')
  const n = Number(qty)
  if (!Number.isInteger(n) || n <= 0) return t('approval.errPositive')
  if (side === 'buy' && n % LOT_SIZE !== 0) return t('approval.errLot', { lot: LOT_SIZE })
  return null
}

/** Human-in-the-loop gate: approve / reject / modify quantity of the proposed order. */
export function ApprovalCard({
  runId,
  order,
  riskCheck,
  onSubmitted,
}: {
  runId: string
  order: OrderProposal | null
  riskCheck: RiskCheck | null
  onSubmitted?: () => void
}) {
  const t = useT()
  const ids = { qty: useId(), comment: useId() }
  const approve = useApproveRun(runId)
  const [modifying, setModifying] = useState(false)
  const [qty, setQty] = useState(order ? String(order.quantity) : '')
  const [comment, setComment] = useState('')
  const [touched, setTouched] = useState(false)

  const qtyError = modifying && touched ? validateQty(t, qty, order?.side) : null
  const pending = approve.isPending ? approve.variables?.action : undefined

  const submit = (action: ApprovalAction) => {
    if (action === 'modify') {
      setTouched(true)
      if (validateQty(t, qty, order?.side)) return
    }
    approve.mutate(
      { action, quantity: action === 'modify' ? Number(qty) : null, comment: comment.trim() || null },
      {
        onSuccess: () => {
          toast.success(
            action === 'reject' ? t('approval.doneRejected') : t('approval.doneApproved'),
            action === 'modify' ? t('approval.doneModified', { n: fmtShares(Number(qty)) }) : undefined,
          )
          onSubmitted?.()
        },
      },
    )
  }

  const blocks = riskCheck?.violations.length ?? 0
  const warns = riskCheck?.warnings.length ?? 0

  return (
    <Card className="border-warn/50 ring-4 ring-warn/10">
      <CardHeader
        title={t('approval.title')}
        icon={<UserCheck />}
        subtitle={t('approval.subtitle')}
        actions={
          <Badge tone="warn" dot pulse>
            {t('approval.waiting')}
          </Badge>
        }
      />
      <CardBody className="space-y-4">
        {order ? <OrderTable order={order} /> : <p className="text-sm text-muted">{t('approval.noOrder')}</p>}

        {(blocks > 0 || warns > 0) && (
          <p className="text-xs text-muted">
            {t('approval.riskPrefix')}
            {blocks > 0 && <span className="text-up">{t('approval.riskBlocks', { n: blocks })}</span>}
            {warns > 0 && <span className="text-warn">{t('approval.riskWarns', { n: warns })}</span>}
            {t('approval.riskSuffix')}
          </p>
        )}

        {modifying && order && (
          <Field
            label={order.side === 'buy' ? t('approval.qtyBuy') : t('approval.qtySell')}
            htmlFor={ids.qty}
            error={qtyError}
          >
            <div className="flex items-center gap-2">
              <Button
                size="icon"
                aria-label={t('approval.minus')}
                onClick={() => setQty((q) => String(Math.max(LOT_SIZE, (Number(q) || 0) - LOT_SIZE)))}
              >
                −
              </Button>
              <Input
                id={ids.qty}
                type="number"
                inputMode="numeric"
                min={order.side === 'buy' ? LOT_SIZE : 1}
                step={LOT_SIZE}
                value={qty}
                onChange={(e) => setQty(e.target.value)}
                onBlur={() => setTouched(true)}
                className="max-w-40 text-center font-mono"
              />
              <Button
                size="icon"
                aria-label={t('approval.plus')}
                onClick={() => setQty((q) => String((Number(q) || 0) + LOT_SIZE))}
              >
                +
              </Button>
              <span className="text-xs text-muted">{t('approval.original', { n: fmtShares(order.quantity) })}</span>
            </div>
          </Field>
        )}

        <Field label={t('approval.comment')} htmlFor={ids.comment}>
          <textarea
            id={ids.comment}
            rows={2}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder={t('approval.commentPlaceholder')}
            className={cn(inputClass, 'h-auto resize-y py-2')}
          />
        </Field>

        <div className="flex flex-wrap gap-2">
          {modifying ? (
            <>
              <Button
                variant="primary"
                icon={<Check className="size-4" />}
                loading={pending === 'modify'}
                disabled={approve.isPending}
                onClick={() => submit('modify')}
              >
                {t('approval.approveModified')}
              </Button>
              <Button variant="ghost" disabled={approve.isPending} onClick={() => setModifying(false)}>
                {t('approval.cancelModify')}
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="primary"
                icon={<Check className="size-4" />}
                loading={pending === 'approve'}
                disabled={approve.isPending}
                onClick={() => submit('approve')}
              >
                {t('approval.approve')}
              </Button>
              {order && (
                <Button icon={<Pencil className="size-4" />} disabled={approve.isPending} onClick={() => setModifying(true)}>
                  {t('approval.modify')}
                </Button>
              )}
              <Button
                icon={<X className="size-4" />}
                loading={pending === 'reject'}
                disabled={approve.isPending}
                onClick={() => submit('reject')}
                className="hover:border-up/50 hover:text-up"
              >
                {t('approval.reject')}
              </Button>
            </>
          )}
        </div>
      </CardBody>
    </Card>
  )
}
