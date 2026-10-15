import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { api, ApiError, errorFromResponse, rawFetch } from './client'
import {
  RUN_EVENT_TYPES,
  type ChatEvent,
  type ChatEventType,
  type ChatRequest,
  type Execution,
  type OrderProposal,
  type Rating,
  type ReportKey,
  type RiskCheck,
  type RunEvent,
  type RunEventPayloads,
  type RunEventType,
  type RunStatus,
} from './types'
import { translate } from '@/i18n/store'
import { REPORTS, type NodeName } from '@/lib/constants'
import { speakerSide, stripSpeaker, type DebateTurn } from '@/lib/debate'

// ===========================================================================
// Generic SSE parser for fetch() bodies (EventSource cannot POST)
// ===========================================================================

export interface SSEMessage {
  event: string
  data: string
  id: string | null
}

/**
 * Parse a `text/event-stream` body per the WHATWG spec: CR / LF / CRLF line
 * endings (also split across chunks), `event:` / `data:` / `id:` fields,
 * multi-line `data:` joined with "\n", comment lines starting with ":".
 */
export async function readSSE(
  body: ReadableStream<Uint8Array>,
  onMessage: (msg: SSEMessage) => void,
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buf = ''
  let event = ''
  let data: string[] = []
  let lastId: string | null = null

  const dispatch = () => {
    if (data.length > 0) onMessage({ event: event || 'message', data: data.join('\n'), id: lastId })
    event = ''
    data = []
  }

  const processLine = (line: string) => {
    if (line === '') return dispatch()
    if (line.startsWith(':')) return
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') event = value
    else if (field === 'data') data.push(value)
    else if (field === 'id' && !value.includes('\0')) lastId = value
    // "retry" and unknown fields are ignored
  }

  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      // stream: true keeps multi-byte (Chinese) characters split across chunks intact
      buf += decoder.decode(value, { stream: true })
      let start = 0
      for (let i = 0; i < buf.length; i++) {
        const c = buf[i]
        if (c !== '\n' && c !== '\r') continue
        // A trailing CR may be the first half of a CRLF split across chunks: wait.
        if (c === '\r' && i === buf.length - 1) break
        processLine(buf.slice(start, i))
        if (c === '\r' && buf[i + 1] === '\n') i++
        start = i + 1
      }
      buf = buf.slice(start)
    }
    buf += decoder.decode()
    if (buf) processLine(buf.replace(/\r$/, ''))
    dispatch() // be lenient with a final event missing its blank line
  } finally {
    reader.releaseLock()
  }
}

function parseJson(text: string): unknown {
  if (!text) return {}
  try {
    return JSON.parse(text)
  } catch {
    return { text }
  }
}

const CHAT_EVENT_TYPES: ReadonlySet<string> = new Set<ChatEventType>([
  'token',
  'tool_call',
  'tool_result',
  'citations',
  'done',
  'error',
])

/**
 * POST /api/research/chat and stream its SSE response. Resolves when the
 * stream ends; rejects with ApiError on HTTP errors, or AbortError when
 * `signal` aborts.
 */
export async function streamChat(
  body: ChatRequest,
  onEvent: (ev: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await rawFetch(api.chatUrl(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) throw await errorFromResponse(res)
  if (!res.body) throw new ApiError(res.status, translate('http.noStream'))

  await readSSE(res.body, (msg) => {
    if (!CHAT_EVENT_TYPES.has(msg.event)) return
    // JSON boundary: the payload shape is the server's contract
    onEvent({ type: msg.event, data: parseJson(msg.data) } as ChatEvent)
  })
}

// ===========================================================================
// Run events: EventSource -> typed reducer
// ===========================================================================

export type ConnectionState = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed' | 'error'

export interface ToolCallState {
  tool: string
  args: Record<string, unknown>
  preview?: string
  ts: string
}

export interface LiveNode {
  name: string
  status: 'running' | 'done'
  /** Streamed text of the node's current (latest) turn. */
  text: string
  /** Markdown deliverable once filed (report / plan / decision / debate turn). */
  final?: string
  /** How many times the node started (debaters speak once per round). */
  turns: number
  tools: ToolCallState[]
  startedAt?: string
  endedAt?: string
  /** Error message from the node's `end` event, if it failed. */
  error?: string
}

export interface LiveDebateTurn extends DebateTurn {
  ts: string
}

export interface RunLiveState {
  connection: ConnectionState
  /** The server sent `done` (or the stream finished). */
  done: boolean
  status: RunStatus | null
  nodes: Record<string, LiveNode>
  reports: Partial<Record<ReportKey, { title: string; content: string }>>
  debates: { investment: LiveDebateTurn[]; risk: LiveDebateTurn[] }
  plans: { investment_plan?: string; trader_plan?: string }
  decision: { rating: Rating; content: string } | null
  riskCheck: RiskCheck | null
  approvalRequired: { order: OrderProposal; risk_check: RiskCheck } | null
  approval: RunEventPayloads['approval'] | null
  execution: Execution | null
  memory: RunEventPayloads['memory'] | null
  errors: string[]
  eventCount: number
  lastEventAt: string | null
}

export const initialRunLiveState: RunLiveState = {
  connection: 'idle',
  done: false,
  status: null,
  nodes: {},
  reports: {},
  debates: { investment: [], risk: [] },
  plans: {},
  decision: null,
  riskCheck: null,
  approvalRequired: null,
  approval: null,
  execution: null,
  memory: null,
  errors: [],
  eventCount: 0,
  lastEventAt: null,
}

type Action =
  | { type: 'reset' }
  | { type: 'connection'; value: ConnectionState }
  | { type: 'events'; events: RunEvent[] }

const REPORT_NODE: Record<string, NodeName> = Object.fromEntries(REPORTS.map((r) => [r.key, r.node]))

function debateNode(stage: 'investment' | 'risk', speaker: string): NodeName | null {
  switch (speakerSide(speaker)) {
    case 'bull':
      return 'Bull Researcher'
    case 'bear':
      return 'Bear Researcher'
    case 'aggressive':
      return 'Aggressive Analyst'
    case 'conservative':
      return 'Conservative Analyst'
    case 'neutral':
      return 'Neutral Analyst'
    case 'judge':
      return stage === 'investment' ? 'Research Manager' : 'Portfolio Manager'
    default:
      return null
  }
}

function ensureNode(
  nodes: Record<string, LiveNode>,
  name: string,
  ts: string,
  status: LiveNode['status'] = 'running',
): LiveNode {
  return nodes[name] ?? { name, status, text: '', turns: 1, tools: [], startedAt: ts }
}

function withNode(
  s: RunLiveState,
  name: string,
  ts: string,
  update: (n: LiveNode) => LiveNode,
  status: LiveNode['status'] = 'running',
): RunLiveState {
  return { ...s, nodes: { ...s.nodes, [name]: update(ensureNode(s.nodes, name, ts, status)) } }
}

function setFinal(s: RunLiveState, name: string | null, content: string, ts: string): RunLiveState {
  if (!name) return s
  // A deliverable can arrive for a node we never saw start (truncated history,
  // or a node that files its output without node events): it is finished.
  return withNode(s, name, ts, (n) => ({ ...n, final: content }), 'done')
}

function applyEvent(s: RunLiveState, ev: RunEvent): RunLiveState {
  const ts = ev.ts
  const base: RunLiveState = { ...s, eventCount: s.eventCount + 1, lastEventAt: ts }

  switch (ev.type) {
    case 'status':
      return { ...base, status: ev.data.status }

    case 'node': {
      const { node, phase } = ev.data
      if (phase === 'start') {
        const prev = base.nodes[node]
        const next: LiveNode = prev
          ? { ...prev, status: 'running', text: '', turns: prev.turns + 1, startedAt: ts, endedAt: undefined, error: undefined }
          : { name: node, status: 'running', text: '', turns: 1, tools: [], startedAt: ts }
        return { ...base, nodes: { ...base.nodes, [node]: next } }
      }
      return withNode(base, node, ts, (n) => ({ ...n, status: 'done', endedAt: ts, error: ev.data.error ?? undefined }))
    }

    case 'token':
      return withNode(base, ev.data.node, ts, (n) => ({ ...n, text: n.text + ev.data.text }))

    case 'tool_call':
      return withNode(base, ev.data.node, ts, (n) => ({
        ...n,
        tools: [...n.tools, { tool: ev.data.tool, args: ev.data.args ?? {}, ts }],
      }))

    case 'tool_result':
      return withNode(base, ev.data.node, ts, (n) => {
        const tools = [...n.tools]
        // attach to the latest call of that tool still waiting for a result
        for (let i = tools.length - 1; i >= 0; i--) {
          const t = tools[i]
          if (t && t.tool === ev.data.tool && t.preview === undefined) {
            tools[i] = { ...t, preview: ev.data.preview }
            return { ...n, tools }
          }
        }
        return { ...n, tools: [...tools, { tool: ev.data.tool, args: {}, preview: ev.data.preview, ts }] }
      })

    case 'report': {
      const next = { ...base, reports: { ...base.reports, [ev.data.key]: { title: ev.data.title, content: ev.data.content } } }
      return setFinal(next, REPORT_NODE[ev.data.key] ?? null, ev.data.content, ts)
    }

    case 'debate': {
      const { stage, speaker } = ev.data
      const content = stripSpeaker(ev.data.content ?? '')
      const turn: LiveDebateTurn = { speaker, side: speakerSide(speaker), content, ts }
      const next = { ...base, debates: { ...base.debates, [stage]: [...base.debates[stage], turn] } }
      return setFinal(next, debateNode(stage, speaker), content, ts)
    }

    case 'plan': {
      const next = { ...base, plans: { ...base.plans, [ev.data.kind]: ev.data.content } }
      return setFinal(next, ev.data.kind === 'investment_plan' ? 'Research Manager' : 'Trader', ev.data.content, ts)
    }

    case 'decision':
      return setFinal({ ...base, decision: ev.data }, 'Portfolio Manager', ev.data.content, ts)

    case 'risk_check':
      return { ...base, riskCheck: ev.data }

    case 'approval_required':
      return { ...base, approvalRequired: ev.data, riskCheck: ev.data.risk_check, status: 'awaiting_approval' }

    case 'approval':
      return { ...base, approval: ev.data }

    case 'execution':
      return { ...base, execution: ev.data }

    case 'memory':
      return { ...base, memory: ev.data }

    case 'done':
      return { ...base, done: true, status: ev.data.status ?? base.status }

    case 'error':
      return { ...base, errors: [...base.errors, ev.data.message] }

    default:
      return base
  }
}

function reducer(state: RunLiveState, action: Action): RunLiveState {
  switch (action.type) {
    case 'reset':
      return initialRunLiveState
    case 'connection':
      return state.connection === action.value ? state : { ...state, connection: action.value }
    case 'events':
      return action.events.reduce(applyEvent, state)
  }
}

/** Redis stream ids look like "1718000000000-3"; compare them numerically. */
function compareStreamId(a: string, b: string): number | null {
  const pa = /^(\d+)-(\d+)$/.exec(a)
  const pb = /^(\d+)-(\d+)$/.exec(b)
  if (!pa || !pb) return null
  const d = Number(pa[1]) - Number(pb[1])
  return d !== 0 ? d : Number(pa[2]) - Number(pb[2])
}

const RUN_EVENT_SET: ReadonlySet<string> = new Set<RunEventType>(RUN_EVENT_TYPES)

function toRunEvent(type: string, raw: string, runId: string): RunEvent | null {
  const parsed = parseJson(raw)
  if (!parsed || typeof parsed !== 'object') return null
  const obj = parsed as Record<string, unknown>
  // Envelope is {type, run_id, ts, data}; tolerate a bare payload as well.
  const hasEnvelope = 'data' in obj && typeof obj.data === 'object' && obj.data !== null
  const evType = typeof obj.type === 'string' && RUN_EVENT_SET.has(obj.type) ? obj.type : type
  if (!RUN_EVENT_SET.has(evType)) return null
  return {
    type: evType,
    run_id: typeof obj.run_id === 'string' ? obj.run_id : runId,
    ts: typeof obj.ts === 'string' ? obj.ts : new Date().toISOString(),
    data: hasEnvelope ? obj.data : obj,
  } as RunEvent // JSON boundary
}

export interface UseRunEventsOptions {
  enabled?: boolean
  /** Called for every event as it arrives (before batching into state). */
  onEvent?: (ev: RunEvent) => void
  /** Called once when the server sends `done`. */
  onDone?: (status: RunStatus | null) => void
}

/**
 * Subscribe to GET /api/runs/{id}/events. The server replays the run's
 * history, then streams live, then sends `done` and closes for terminal runs.
 * Events are batched per animation frame so token floods stay cheap.
 */
export function useRunEvents(runId: string | undefined, opts: UseRunEventsOptions = {}) {
  const { enabled = true } = opts
  const [state, dispatch] = useReducer(reducer, initialRunLiveState)
  const [nonce, setNonce] = useState(0)

  const onEventRef = useRef(opts.onEvent)
  const onDoneRef = useRef(opts.onDone)
  useEffect(() => {
    onEventRef.current = opts.onEvent
    onDoneRef.current = opts.onDone
  })

  useEffect(() => {
    if (!runId || !enabled || typeof EventSource === 'undefined') return

    dispatch({ type: 'reset' })
    dispatch({ type: 'connection', value: 'connecting' })

    const es = new EventSource(api.runEventsUrl(runId))
    let lastId: string | null = null
    const seen = new Set<string>()
    let queue: RunEvent[] = []
    let frame = 0
    let timer: ReturnType<typeof setTimeout> | undefined
    let finished = false

    const flush = () => {
      frame = 0
      timer = undefined
      if (queue.length === 0) return
      const events = queue
      queue = []
      dispatch({ type: 'events', events })
    }
    const schedule = () => {
      if (frame || timer) return
      // rAF is paused in background tabs; fall back to a timer there.
      if (document.hidden) timer = setTimeout(flush, 200)
      else frame = requestAnimationFrame(flush)
    }

    const handle = (type: string, msg: MessageEvent<string>) => {
      const id = msg.lastEventId
      if (id) {
        // Drop replays if the server ever resends history after a reconnect.
        const cmp = lastId ? compareStreamId(id, lastId) : null
        if (cmp !== null ? cmp <= 0 : seen.has(id)) return
        lastId = id
        if (cmp === null) seen.add(id)
      }
      const ev = toRunEvent(type, msg.data, runId)
      if (!ev) return
      onEventRef.current?.(ev)
      queue.push(ev)
      if (ev.type === 'done') {
        finished = true
        es.close()
        flush()
        dispatch({ type: 'connection', value: 'closed' })
        onDoneRef.current?.(ev.data.status ?? null)
      } else {
        schedule()
      }
    }

    const listeners: Array<[string, (e: Event) => void]> = []
    for (const type of RUN_EVENT_TYPES) {
      if (type === 'error') continue
      const fn = (e: Event) => handle(type, e as MessageEvent<string>)
      es.addEventListener(type, fn)
      listeners.push([type, fn])
    }
    // Unnamed messages: the type is inside the JSON envelope.
    const onMessage = (e: MessageEvent<string>) => handle('message', e)
    es.addEventListener('message', onMessage)

    // "error" is both the server's `event: error` (a MessageEvent with data)
    // and the EventSource connection-error signal (a plain Event).
    const onError = (e: Event) => {
      if (e instanceof MessageEvent && typeof e.data === 'string' && e.data) {
        handle('error', e as MessageEvent<string>)
        return
      }
      if (finished) return
      dispatch({ type: 'connection', value: es.readyState === EventSource.CLOSED ? 'error' : 'reconnecting' })
    }
    es.addEventListener('error', onError)
    const onOpen = () => dispatch({ type: 'connection', value: 'open' })
    es.addEventListener('open', onOpen)

    return () => {
      for (const [type, fn] of listeners) es.removeEventListener(type, fn)
      es.removeEventListener('message', onMessage)
      es.removeEventListener('error', onError)
      es.removeEventListener('open', onOpen)
      es.close()
      if (frame) cancelAnimationFrame(frame)
      if (timer) clearTimeout(timer)
    }
  }, [runId, enabled, nonce])

  /** Re-open the stream (the server replays history, so state restarts clean). */
  const reconnect = useCallback(() => setNonce((n) => n + 1), [])

  return { state, reconnect }
}
