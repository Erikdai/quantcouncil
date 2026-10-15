import type { ReactNode } from 'react'
import { AlertTriangle, Inbox, RotateCw } from 'lucide-react'
import { errorMessage } from '@/api/client'
import { useT } from '@/i18n/I18nProvider'
import { cn } from '@/lib/cn'
import { Button } from './Button'

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn('animate-pulse rounded-md bg-surface-3', className)} />
}

/** A few skeleton lines, for list/table placeholders. */
export function SkeletonRows({ rows = 4, className }: { rows?: number; className?: string }) {
  const t = useT()
  return (
    <div className={cn('space-y-2.5', className)} aria-busy="true" aria-label={t('common.loading')}>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={cn('h-9', i % 3 === 2 ? 'w-4/5' : 'w-full')} />
      ))}
    </div>
  )
}

interface EmptyStateProps {
  icon?: ReactNode
  title: string
  description?: ReactNode
  action?: ReactNode
  className?: string
}

export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div className={cn('flex flex-col items-center justify-center px-4 py-10 text-center', className)}>
      <div className="mb-3 flex size-10 items-center justify-center rounded-full bg-surface-2 text-muted [&>svg]:size-5">
        {icon ?? <Inbox />}
      </div>
      <p className="text-sm font-medium text-fg">{title}</p>
      {description && <p className="mt-1 max-w-sm text-xs text-muted">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function ErrorState({
  error,
  title,
  onRetry,
  className,
}: {
  error: unknown
  title?: string
  onRetry?: () => void
  className?: string
}) {
  const t = useT()
  return (
    <div className={cn('flex flex-col items-center justify-center px-4 py-8 text-center', className)} role="alert">
      <div className="mb-3 flex size-10 items-center justify-center rounded-full bg-warn/10 text-warn">
        <AlertTriangle className="size-5" />
      </div>
      <p className="text-sm font-medium text-fg">{title ?? t('common.loadFailed')}</p>
      <p className="mt-1 max-w-sm text-xs break-all text-muted">{errorMessage(error)}</p>
      {onRetry && (
        <Button size="sm" className="mt-4" onClick={onRetry} icon={<RotateCw className="size-3.5" />}>
          {t('common.retry')}
        </Button>
      )}
    </div>
  )
}
