import { useRef, useState } from 'react'
import { RecentRuns } from '@/components/dashboard/RecentRuns'
import { RunForm } from '@/components/dashboard/RunForm'
import { Watchlist } from '@/components/dashboard/Watchlist'
import { ExportMenu } from '@/components/common/ExportMenu'
import { PageHeader } from '@/components/layout/PageHeader'
import { useT } from '@/i18n/I18nProvider'

export default function DashboardPage() {
  const t = useT()
  const [ticker, setTicker] = useState('')
  const tickerRef = useRef<HTMLInputElement>(null)

  const analyze = (value: string) => {
    setTicker(value)
    tickerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    tickerRef.current?.focus({ preventScroll: true })
  }

  return (
    <>
      <PageHeader
        title={t('dash.title')}
        description={t('dash.desc')}
        actions={<ExportMenu target={{ kind: 'daily' }} />}
      />
      {/* Mobile order: form, runs, watchlist. Desktop: form left, runs + watchlist stacked right. */}
      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)] xl:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
        <div className="lg:col-start-1 lg:row-span-2 lg:row-start-1">
          <RunForm ticker={ticker} onTickerChange={setTicker} tickerRef={tickerRef} />
        </div>
        <div className="min-w-0 lg:col-start-2 lg:row-start-1">
          <RecentRuns />
        </div>
        <div className="min-w-0 lg:col-start-2 lg:row-start-2">
          <Watchlist onAnalyze={analyze} />
        </div>
      </div>
    </>
  )
}
