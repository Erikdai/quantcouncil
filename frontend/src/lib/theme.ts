import { useSyncExternalStore } from 'react'

/**
 * Theme preference store. "system" follows prefers-color-scheme; the choice is
 * persisted in localStorage (best effort: storage can be unavailable) and the
 * resolved theme is applied as the `dark` class on <html> (index.html applies
 * it once before first paint to avoid a flash).
 */

export type ThemePref = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

const STORAGE_KEY = 'finagent-theme'
const media = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null

function readPref(): ThemePref {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'light' || v === 'dark' || v === 'system') return v
  } catch {
    // storage blocked (private mode, sandbox): fall through
  }
  return 'system'
}

function resolve(pref: ThemePref): ResolvedTheme {
  if (pref === 'system') return media?.matches ? 'dark' : 'light'
  return pref
}

interface ThemeState {
  pref: ThemePref
  resolved: ResolvedTheme
}

let state: ThemeState = (() => {
  const pref = readPref()
  return { pref, resolved: resolve(pref) }
})()

const listeners = new Set<() => void>()

function apply() {
  const root = document.documentElement
  root.classList.toggle('dark', state.resolved === 'dark')
  root.style.colorScheme = state.resolved
}

function emit(next: ThemeState) {
  state = next
  apply()
  listeners.forEach((l) => l())
}

media?.addEventListener('change', () => {
  if (state.pref === 'system') emit({ pref: 'system', resolved: resolve('system') })
})

export function setThemePref(pref: ThemePref) {
  try {
    localStorage.setItem(STORAGE_KEY, pref)
  } catch {
    // not persisted; still applied for this session
  }
  emit({ pref, resolved: resolve(pref) })
}

function subscribe(cb: () => void) {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

export function useTheme(): ThemeState & { setPref: (p: ThemePref) => void } {
  const snapshot = useSyncExternalStore(subscribe, () => state)
  return { ...snapshot, setPref: setThemePref }
}

/** Read a CSS custom property from :root (used to feed theme colours to canvas charts). */
export function cssVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}
