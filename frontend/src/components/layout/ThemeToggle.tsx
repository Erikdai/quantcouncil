import { Monitor, Moon, Sun } from 'lucide-react'
import { useT } from '@/i18n/I18nProvider'
import { useTheme, type ThemePref } from '@/lib/theme'
import { cn } from '@/lib/cn'

const NEXT: Record<ThemePref, ThemePref> = { system: 'light', light: 'dark', dark: 'system' }
const ICON = { system: Monitor, light: Sun, dark: Moon } satisfies Record<ThemePref, typeof Sun>

/** Cycles system -> light -> dark. */
export function ThemeToggle({ showLabel = false, className }: { showLabel?: boolean; className?: string }) {
  const t = useT()
  const { pref, setPref } = useTheme()
  const Icon = ICON[pref]
  const current = t(`theme.${pref}`)
  return (
    <button
      type="button"
      onClick={() => setPref(NEXT[pref])}
      title={t('theme.title', { current, next: t(`theme.${NEXT[pref]}`) })}
      aria-label={t('theme.aria', { current })}
      className={cn(
        'flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-muted transition hover:bg-surface-2 hover:text-fg',
        className,
      )}
    >
      <Icon className="size-4" />
      {showLabel && <span>{current}</span>}
    </button>
  )
}
