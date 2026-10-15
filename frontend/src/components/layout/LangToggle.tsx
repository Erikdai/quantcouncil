import { useI18n } from '@/i18n/I18nProvider'
import { LANG_LABELS, LANGS } from '@/i18n/store'
import { cn } from '@/lib/cn'

/** Two-segment language switch (Chinese / English); the choice is persisted by the i18n store. */
export function LangToggle({ className }: { className?: string }) {
  const { lang, setLang, t } = useI18n()
  return (
    <div
      role="group"
      aria-label={t('lang.aria')}
      className={cn('inline-flex rounded-lg border border-line bg-surface-2 p-0.5 text-[11px]', className)}
    >
      {LANGS.map((l) => (
        <button
          key={l}
          type="button"
          lang={l === 'zh' ? 'zh-CN' : 'en'}
          aria-pressed={lang === l}
          onClick={() => setLang(l)}
          className={cn(
            'min-w-7 rounded-md px-1.5 py-0.5 font-medium transition',
            lang === l ? 'bg-surface text-fg shadow-card' : 'text-muted hover:text-fg',
          )}
        >
          {LANG_LABELS[l]}
        </button>
      ))}
    </div>
  )
}
