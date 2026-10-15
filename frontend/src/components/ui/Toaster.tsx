import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react'
import { useT } from '@/i18n/I18nProvider'
import { cn } from '@/lib/cn'
import { dismissToast, useToasts, type ToastKind } from '@/lib/toast'

const ICONS: Record<ToastKind, typeof Info> = { error: AlertCircle, success: CheckCircle2, info: Info }
const ICON_COLOR: Record<ToastKind, string> = { error: 'text-up', success: 'text-ok', info: 'text-info' }

export function Toaster() {
  const toasts = useToasts()
  const t = useT()
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-3 bottom-3 z-[60] flex flex-col items-end gap-2 sm:inset-x-auto sm:right-5 sm:bottom-5 sm:w-96"
    >
      {toasts.map((item) => {
        const Icon = ICONS[item.kind]
        return (
          <div
            key={item.id}
            role={item.kind === 'error' ? 'alert' : 'status'}
            className="pointer-events-auto flex w-full animate-slide-in items-start gap-3 rounded-xl border border-line bg-surface p-3 shadow-xl"
          >
            <Icon className={cn('mt-0.5 size-4 shrink-0', ICON_COLOR[item.kind])} />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-fg">{item.title}</p>
              {item.message && <p className="mt-0.5 text-xs break-words text-muted">{item.message}</p>}
            </div>
            <button
              type="button"
              onClick={() => dismissToast(item.id)}
              className="rounded p-0.5 text-muted hover:text-fg"
              aria-label={t('common.dismiss')}
            >
              <X className="size-3.5" />
            </button>
          </div>
        )
      })}
    </div>
  )
}
