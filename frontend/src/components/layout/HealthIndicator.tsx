import { useEffect, useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { useHealth } from '@/hooks/api'
import { useI18n } from '@/i18n/I18nProvider'
import { cn } from '@/lib/cn'

function isOk(v: string) {
  const s = v.toLowerCase()
  return s === 'ok' || s === 'up' || s === 'healthy' || s === 'true' || s === 'enabled'
}

type HealthState = 'pending' | 'down' | 'ok' | 'degraded'

const DOT: Record<HealthState, string> = { pending: 'bg-muted', down: 'bg-up', ok: 'bg-ok', degraded: 'bg-warn' }

/** Header dot: green ok / amber degraded / red unreachable, with a services popover. */
export function HealthIndicator({ compact = false }: { compact?: boolean }) {
  const { t, tx } = useI18n()
  const { data, isError, isPending } = useHealth()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const state: HealthState = isPending ? 'pending' : isError || !data ? 'down' : data.status === 'ok' ? 'ok' : 'degraded'
  const label = t(`health.${state}`)

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={t('health.aria', { label })}
        className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-muted hover:bg-surface-2 hover:text-fg"
      >
        <span className="relative flex size-2">
          {state === 'ok' && (
            <span className={cn('absolute inline-flex size-full animate-ping rounded-full opacity-40', DOT[state])} />
          )}
          <span className={cn('relative inline-flex size-2 rounded-full', DOT[state])} />
        </span>
        {!compact && <span>{label}</span>}
        <ChevronDown className="size-3" />
      </button>

      {open && (
        <div className="absolute right-0 z-40 mt-1 w-64 animate-fade-in rounded-xl border border-line bg-surface p-3 shadow-xl">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-semibold text-fg">{t('health.title')}</span>
            {data?.version && <span className="font-mono text-[11px] text-muted">v{data.version}</span>}
          </div>
          {state === 'down' && <p className="text-xs text-muted">{t('health.unreachable')}</p>}
          {data && (
            <ul className="space-y-1.5">
              {Object.entries(data.services).map(([name, value]) => (
                <li key={name} className="flex items-center justify-between gap-3 text-xs">
                  <span className="text-fg-2">{tx(`service.${name.toLowerCase()}`, name)}</span>
                  <span className={cn('truncate font-mono', isOk(value) ? 'text-ok' : 'text-warn')} title={value}>
                    {value}
                  </span>
                </li>
              ))}
              {Object.keys(data.services).length === 0 && <li className="text-xs text-muted">{t('health.noServices')}</li>}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
