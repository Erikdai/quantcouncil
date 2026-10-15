import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/cn'

export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-xl border border-line bg-surface shadow-card', className)} {...rest} />
}

interface CardHeaderProps {
  title: ReactNode
  icon?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  className?: string
}

export function CardHeader({ title, icon, subtitle, actions, className }: CardHeaderProps) {
  return (
    <div className={cn('flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-4 py-3', className)}>
      <div className="flex min-w-0 flex-1 items-center gap-2">
        {icon && <span className="text-muted [&>svg]:size-4">{icon}</span>}
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold text-fg">{title}</h2>
          {subtitle && <p className="truncate text-xs text-muted">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

export function CardBody({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('p-4', className)} {...rest} />
}
