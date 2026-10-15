import { useEffect, useId, useRef, useState } from 'react'
import { Download, FileText, FileType } from 'lucide-react'
import { api, errorMessage } from '@/api/client'
import type { ExportFormat } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { Field, Input } from '@/components/ui/Controls'
import { useRuns } from '@/hooks/api'
import { useI18n } from '@/i18n/I18nProvider'
import { toast } from '@/lib/toast'

type ExportTarget = { kind: 'daily' } | { kind: 'run'; runId: string }

/** Date field for the daily report, defaulting to the latest analysed trade date. */
function DailyDate({ day, onChange }: { day: string; onChange: (v: string) => void }) {
  const { t } = useI18n()
  const id = useId()
  const runs = useRuns(null, 30)
  const touched = useRef(false)
  const latest = runs.data?.reduce<string>((max, r) => (r.trade_date > max ? r.trade_date : max), '') ?? ''

  // Fill the default once the runs arrive, unless the user already picked a date.
  useEffect(() => {
    if (latest && !touched.current && !day) onChange(latest)
  }, [latest, day, onChange])

  return (
    <Field label={t('export.day')} htmlFor={id} hint={t('export.dayHint')}>
      <Input
        id={id}
        type="date"
        value={day}
        onChange={(e) => {
          touched.current = true
          onChange(e.target.value)
        }}
      />
    </Field>
  )
}

/** "Export" button with a PDF / Word choice; the report language follows the UI language. */
export function ExportMenu({ target, size = 'md' }: { target: ExportTarget; size?: 'sm' | 'md' }) {
  const { t, lang } = useI18n()
  const [open, setOpen] = useState(false)
  const [day, setDay] = useState('')
  const [pending, setPending] = useState<ExportFormat | null>(null)
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

  const run = async (format: ExportFormat) => {
    setPending(format)
    try {
      const file =
        target.kind === 'daily'
          ? await api.exportDaily({ format, lang, day: day || null })
          : await api.exportRun(target.runId, { format, lang })
      toast.success(t('export.done', { file }))
      setOpen(false)
    } catch (err) {
      toast.error(t('err.export'), errorMessage(err))
    } finally {
      setPending(null)
    }
  }

  return (
    <div ref={ref} className="relative">
      <Button
        size={size}
        icon={<Download className="size-4" />}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((o) => !o)}
      >
        {target.kind === 'daily' ? t('export.daily') : t('export.run')}
      </Button>
      {open && (
        <div
          role="dialog"
          aria-label={target.kind === 'daily' ? t('export.daily') : t('export.run')}
          className="absolute right-0 z-40 mt-1 w-72 max-w-[calc(100vw-2rem)] animate-fade-in space-y-3 rounded-xl border border-line bg-surface p-3 shadow-xl"
        >
          {target.kind === 'daily' && <DailyDate day={day} onChange={setDay} />}
          <div className="grid grid-cols-2 gap-2">
            <Button
              className="justify-center"
              icon={<FileText className="size-4" />}
              loading={pending === 'pdf'}
              disabled={pending !== null}
              onClick={() => void run('pdf')}
            >
              {t('export.pdf')}
            </Button>
            <Button
              className="justify-center"
              icon={<FileType className="size-4" />}
              loading={pending === 'docx'}
              disabled={pending !== null}
              onClick={() => void run('docx')}
            >
              {t('export.word')}
            </Button>
          </div>
          <p className="text-[11px] text-muted">{t('export.langNote')}</p>
        </div>
      )}
    </div>
  )
}
