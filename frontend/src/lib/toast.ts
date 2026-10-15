import { useSyncExternalStore } from 'react'

/**
 * Tiny global toast store. Lives outside React so non-component code (React
 * Query's MutationCache, SSE handlers) can raise toasts too.
 */

export type ToastKind = 'error' | 'success' | 'info'

export interface Toast {
  id: number
  kind: ToastKind
  title: string
  message?: string
}

let toasts: Toast[] = []
let nextId = 1
const listeners = new Set<() => void>()
const timers = new Map<number, ReturnType<typeof setTimeout>>()

function emit(next: Toast[]) {
  toasts = next
  listeners.forEach((l) => l())
}

export function dismissToast(id: number) {
  const t = timers.get(id)
  if (t) clearTimeout(t)
  timers.delete(id)
  emit(toasts.filter((x) => x.id !== id))
}

function push(kind: ToastKind, title: string, message?: string, durationMs?: number): number {
  // Collapse duplicates (e.g. the same network error from several queries).
  const dup = toasts.find((t) => t.kind === kind && t.title === title && t.message === message)
  if (dup) dismissToast(dup.id)

  const id = nextId++
  emit([...toasts.slice(-4), { id, kind, title, message }])
  const ms = durationMs ?? (kind === 'error' ? 6000 : 3500)
  timers.set(
    id,
    setTimeout(() => dismissToast(id), ms),
  )
  return id
}

export const toast = {
  error: (title: string, message?: string) => push('error', title, message),
  success: (title: string, message?: string) => push('success', title, message),
  info: (title: string, message?: string) => push('info', title, message),
}

function subscribe(cb: () => void) {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

export function useToasts(): Toast[] {
  return useSyncExternalStore(subscribe, () => toasts)
}
