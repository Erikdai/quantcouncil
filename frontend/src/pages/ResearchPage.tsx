import { useState } from 'react'
import { Filter } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { ChatPanel } from '@/components/research/ChatPanel'
import { DocumentsPanel } from '@/components/research/DocumentsPanel'
import { SearchPanel } from '@/components/research/SearchPanel'
import { Card } from '@/components/ui/Card'
import { Input, Tabs } from '@/components/ui/Controls'
import { useDebounced } from '@/hooks/useDebounced'
import { useT } from '@/i18n/I18nProvider'

type SideTab = 'docs' | 'search'

export default function ResearchPage() {
  const t = useT()
  const [ticker, setTicker] = useState('')
  const [tab, setTab] = useState<SideTab>('docs')
  // Side panels query per ticker; wait until typing pauses.
  const scope = useDebounced(ticker, 400)

  return (
    <>
      <PageHeader
        title={t('research.title')}
        description={t('research.desc')}
        actions={
          <label className="flex items-center gap-2">
            <Filter className="size-4 text-muted" aria-hidden />
            <span className="sr-only">{t('research.scope')}</span>
            <Input
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              placeholder={t('research.scopePlaceholder')}
              className="w-64 font-mono"
              autoComplete="off"
            />
          </label>
        }
      />
      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,400px)]">
        <ChatPanel ticker={ticker} />
        <Card className="min-w-0 overflow-hidden">
          <Tabs
            items={[
              { id: 'docs', label: t('research.tabDocs') },
              { id: 'search', label: t('research.tabSearch') },
            ]}
            value={tab}
            onChange={setTab}
            ariaLabel={t('research.tabsAria')}
          />
          <div className="max-h-[calc(100dvh-14rem)] overflow-y-auto">
            {tab === 'docs' ? <DocumentsPanel ticker={scope} /> : <SearchPanel ticker={scope} />}
          </div>
        </Card>
      </div>
    </>
  )
}
