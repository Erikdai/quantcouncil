import { useCallback, useEffect, useRef, useState } from 'react'
import { errorMessage } from '@/api/client'
import { streamChat } from '@/api/sse'
import type { ChatMessage, Citation } from '@/api/types'

export interface ChatToolCall {
  tool: string
  args: Record<string, unknown>
  preview?: string
}

export interface ChatTurn {
  id: string
  role: 'user' | 'assistant'
  content: string
  tools: ChatToolCall[]
  citations: Citation[]
  status: 'streaming' | 'done' | 'error' | 'aborted'
  error?: string
}

function newId(): string {
  try {
    return crypto.randomUUID()
  } catch {
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
  }
}

/** Streaming research chat over POST /api/research/chat (SSE in the response body). */
export function useResearchChat() {
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const abortRef = useRef<AbortController | null>(null)
  const threadId = useRef(newId())
  const turnsRef = useRef(turns)
  useEffect(() => {
    turnsRef.current = turns
  })
  useEffect(() => () => abortRef.current?.abort(), [])

  const streaming = turns.some((t) => t.status === 'streaming')

  const send = useCallback(async (text: string, ticker: string | null) => {
    const content = text.trim()
    if (!content || abortRef.current) return

    const user: ChatTurn = { id: newId(), role: 'user', content, tools: [], citations: [], status: 'done' }
    const asstId = newId()
    const assistant: ChatTurn = { id: asstId, role: 'assistant', content: '', tools: [], citations: [], status: 'streaming' }

    const history: ChatMessage[] = [...turnsRef.current, user]
      .filter((t) => t.content && t.status !== 'error')
      .map((t) => ({ role: t.role, content: t.content }))

    setTurns((prev) => [...prev, user, assistant])
    const update = (fn: (t: ChatTurn) => ChatTurn) => setTurns((prev) => prev.map((t) => (t.id === asstId ? fn(t) : t)))

    // Coalesce token deltas into one state update per frame.
    let pending = ''
    let frame = 0
    const flush = () => {
      frame = 0
      if (!pending) return
      const add = pending
      pending = ''
      update((t) => ({ ...t, content: t.content + add }))
    }

    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      await streamChat(
        { messages: history, ticker: ticker || null, thread_id: threadId.current },
        (ev) => {
          switch (ev.type) {
            case 'token':
              pending += ev.data.text ?? ''
              if (!frame) frame = requestAnimationFrame(flush)
              break
            case 'tool_call':
              flush()
              update((t) => ({ ...t, tools: [...t.tools, { tool: ev.data.tool, args: ev.data.args ?? {} }] }))
              break
            case 'tool_result':
              update((t) => {
                const tools = [...t.tools]
                const i = tools.findLastIndex((c) => c.tool === ev.data.tool && c.preview === undefined)
                if (i >= 0) tools[i] = { ...tools[i]!, preview: ev.data.preview }
                else tools.push({ tool: ev.data.tool, args: {}, preview: ev.data.preview })
                return { ...t, tools }
              })
              break
            case 'citations':
              // One event per retrieval step: accumulate across steps, skipping repeated passages.
              update((t) => {
                const seen = new Set(t.citations.map((c) => c.chunk_id))
                const fresh = (ev.data.items ?? []).filter((c) => !seen.has(c.chunk_id))
                return { ...t, citations: [...t.citations, ...fresh] }
              })
              break
            case 'error':
              flush()
              update((t) => ({ ...t, status: 'error', error: ev.data.message }))
              break
            case 'done':
              break
          }
        },
        ctrl.signal,
      )
      cancelAnimationFrame(frame)
      flush()
      update((t) => (t.status === 'streaming' ? { ...t, status: 'done' } : t))
    } catch (err) {
      cancelAnimationFrame(frame)
      flush()
      const aborted = ctrl.signal.aborted
      update((t) => ({ ...t, status: aborted ? 'aborted' : 'error', error: aborted ? undefined : errorMessage(err) }))
    } finally {
      abortRef.current = null
    }
  }, [])

  const stop = useCallback(() => abortRef.current?.abort(), [])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    setTurns([])
    threadId.current = newId()
  }, [])

  return { turns, streaming, send, stop, reset }
}
