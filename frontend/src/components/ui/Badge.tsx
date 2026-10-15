import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export type BadgeTone = 'up' | 'down' | 'flat' | 'warn' | 'info' | 'accent' | 'muted' | 'ok'

const TONES: Record<BadgeTone, string> = {
  up: 'bg-up/10 text-up ring-up/25',
  down: 'bg-down/10 text-down ring-down/25',
  flat: 'bg-surface-3 text-fg-2 ring-line-strong/70',
  warn: 'bg-warn/10 text-warn ring-warn/30',
  info: 'bg-info/10 text-info ring-info/25',
  accent: 'bg-accent/10 text-accent ring-accent/25',
  muted: 'bg-surface-2 text-muted ring-line',
  ok: 'bg-ok/10 text-ok ring-ok/25',
}

interface BadgeProps {
  tone?: BadgeTone
  children: ReactNode
  className?: string
  title?: string
  dot?: boolean
  pulse?: boolean
}

export function Badge({ tone = 'muted', children, className, title, dot, pulse }: BadgeProps) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset',
        TONES[tone],
        className,
      )}
    >
      {dot && (
        <span className="relative flex size-1.5">
          {pulse && <span className="absolute inline-flex size-full animate-ping rounded-full bg-current opacity-60" />}
          <span className="relative inline-flex size-1.5 rounded-full bg-current" />
        </span>
      )}
      {children}
    </span>
  )
}
