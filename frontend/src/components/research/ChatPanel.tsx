import { useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { AlertCircle, Bot, ChevronRight, Eraser, Loader2, Send, Square, User, Wrench } from 'lucide-react'
import { Markdown } from '@/components/common/Markdown'
import { Button } from '@/components/ui/Button'
import { Card, CardHeader } from '@/components/ui/Card'
import { inputClass } from '@/components/ui/Controls'
import type { ChatToolCall, ChatTurn } from '@/hooks/useResearchChat'
import { useResearchChat } from '@/hooks/useResearchChat'
import { useT } from '@/i18n/I18nProvider'
import type { MessageKey } from '@/i18n/store'
import { cn } from '@/lib/cn'
import { CitationCard, groupByDocument } from './CitationCard'

const SUGGESTIONS: readonly MessageKey[] = ['chat.suggest1', 'chat.suggest2', 'chat.suggest3']

function ToolChip({ call }: { call: ChatToolCall }) {
  const [open, setOpen] = useState(false)
  const running = call.preview === undefined
  return (
    <div className={cn(open && 'w-full')}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={cn(
          'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[11px] transition',
          running ? 'border-accent/40 bg-accent/5 text-accent' : 'border-line bg-surface-2 text-fg-2 hover:border-line-strong',
        )}
      >
        {running ? <Loader2 className="size-3 animate-spin" /> : <Wrench className="size-3" />}
        {call.tool}
        <ChevronRight className={cn('size-3 transition', open && 'rotate-90')} />
      </button>
      {open && (
        <div className="mt-1.5 space-y-1 rounded-lg border border-line bg-surface-2 p-2 font-mono text-[11px]">
          <div className="break-all text-fg-2">
            <span className="text-muted">args </span>
            {JSON.stringify(call.args)}
          </div>
          {call.preview !== undefined && (
            <pre className="max-h-40 overflow-auto break-words whitespace-pre-wrap text-fg-2">{call.preview}</pre>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * Sources grouped per document. Cards are numbered per document: each tool call numbers its
 * passages from [1] again and the citations event carries no call boundaries, so the answer's
 * [n] cannot be mapped to a card reliably.
 */
function Sources({ turn }: { turn: ChatTurn }) {
  const t = useT()
  const groups = groupByDocument(turn.citations)
  return (
    <div>
      <p className="mb-1.5 text-[11px] font-medium text-muted">
        {t('chat.sources', { docs: groups.length, passages: turn.citations.length })}
      </p>
      <div className="grid gap-1.5 sm:grid-cols-2">
        {groups.map((g, i) => (
          <CitationCard
            key={g.best.document_id}
            index={i + 1}
            citation={g.best}
            extraPassages={g.passages - 1}
            snippet="short"
          />
        ))}
      </div>
    </div>
  )
}

function Message({ turn }: { turn: ChatTurn }) {
  const t = useT()
  if (turn.role === 'user') {
    return (
      <div className="flex justify-end gap-2.5">
        <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-accent px-3.5 py-2 text-sm whitespace-pre-wrap text-accent-fg">
          {turn.content}
        </div>
        <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-surface-3 text-fg-2">
          <User className="size-3.5" />
        </div>
      </div>
    )
  }

  const streaming = turn.status === 'streaming'
  return (
    <div className="flex gap-2.5">
      <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-accent/15 text-accent">
        <Bot className="size-3.5" />
      </div>
      <div className="min-w-0 flex-1 space-y-2">
        {turn.tools.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {turn.tools.map((c, i) => (
              <ToolChip key={`${c.tool}-${i}`} call={c} />
            ))}
          </div>
        )}
        {turn.content ? (
          <Markdown streaming={streaming}>{turn.content}</Markdown>
        ) : streaming ? (
          <p className="flex items-center gap-1.5 text-sm text-muted">
            <Loader2 className="size-3.5 animate-spin" />
            {turn.tools.length ? t('chat.searching') : t('chat.thinking')}
          </p>
        ) : null}
        {turn.status === 'aborted' && <p className="text-xs text-muted">{t('chat.stopped')}</p>}
        {turn.status === 'done' && !turn.content && <p className="text-xs text-muted">{t('chat.noText')}</p>}
        {turn.status === 'error' && (
          <p className="flex items-start gap-1.5 rounded-lg bg-up/[0.06] px-2.5 py-1.5 text-xs text-up">
            <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
            {turn.error ?? t('chat.failed')}
          </p>
        )}
        {turn.citations.length > 0 && <Sources turn={turn} />}
      </div>
    </div>
  )
}

/** RAG research chat: streamed Markdown answers, tool-call chips and numbered citations. */
export function ChatPanel({ ticker }: { ticker: string }) {
  const t = useT()
  const { turns, streaming, send, stop, reset } = useResearchChat()
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  const scope = ticker.trim()

  useLayoutEffect(() => {
    const el = scrollRef.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [turns])

  const submit = (text = input) => {
    if (!text.trim() || streaming) return
    stick.current = true
    void send(text, scope || null)
    setInput('')
  }
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    submit()
  }
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends; Shift+Enter and IME composition keep the newline / candidate selection.
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <Card className="flex h-[72dvh] min-h-[420px] flex-col lg:h-[calc(100dvh-12rem)]">
      <CardHeader
        title={t('chat.title')}
        icon={<Bot />}
        subtitle={scope ? t('chat.scopeTicker', { t: scope }) : t('chat.scopeAll')}
        actions={
          turns.length > 0 && (
            <Button size="sm" variant="ghost" icon={<Eraser className="size-3.5" />} onClick={reset}>
              {t('chat.new')}
            </Button>
          )
        }
      />

      <div
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
        }}
        className="flex-1 space-y-5 overflow-y-auto px-4 py-4"
        aria-live="polite"
      >
        {turns.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <div className="mb-3 flex size-11 items-center justify-center rounded-full bg-accent/10 text-accent">
              <Bot className="size-5" />
            </div>
            <p className="text-sm font-medium text-fg">{t('chat.emptyTitle')}</p>
            <p className="mt-1 max-w-sm text-xs text-muted">{t('chat.emptyDesc')}</p>
            <div className="mt-4 flex max-w-md flex-col gap-2">
              {SUGGESTIONS.map((key) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => submit(t(key))}
                  className="rounded-lg border border-line px-3 py-2 text-left text-xs text-fg-2 transition hover:border-accent hover:text-accent"
                >
                  {t(key)}
                </button>
              ))}
            </div>
          </div>
        ) : (
          turns.map((turn) => <Message key={turn.id} turn={turn} />)
        )}
      </div>

      <form onSubmit={onSubmit} className="flex items-end gap-2 border-t border-line p-3">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder={t('chat.placeholder')}
          aria-label={t('chat.inputAria')}
          className={cn(inputClass, 'field-sizing-content h-auto max-h-36 min-h-9 resize-none py-2')}
        />
        {streaming ? (
          <Button variant="secondary" onClick={stop} icon={<Square className="size-3.5" />}>
            {t('chat.stop')}
          </Button>
        ) : (
          <Button type="submit" variant="primary" disabled={!input.trim()} icon={<Send className="size-4" />}>
            {t('chat.send')}
          </Button>
        )}
      </form>
    </Card>
  )
}
