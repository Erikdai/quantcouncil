import { en } from './en'
import { zh, type MessageKey, type Messages } from './zh'

/**
 * Current UI language, kept outside React so non-component code (API errors,
 * React Query toasts, number/date formatters) can translate too. Components
 * read it through <I18nProvider> / useT(), which re-render on change.
 */

export type Lang = 'zh' | 'en'
export type Params = Record<string, string | number>
export type { MessageKey, Messages }

export const LANGS: readonly Lang[] = ['zh', 'en']
/** Toggle labels: each language's own short name, identical in both UIs. */
export const LANG_LABELS: Record<Lang, string> = { zh: '中', en: 'EN' }

const STORAGE_KEY = 'quantcouncil-lang'
const DICTS: Record<Lang, Messages> = { zh, en }

function detect(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'zh' || saved === 'en') return saved
  } catch {
    // storage blocked: fall back to the browser language
  }
  const nav = typeof navigator !== 'undefined' ? navigator.language : ''
  return nav.toLowerCase().startsWith('zh') ? 'zh' : 'en'
}

let lang: Lang = detect()
const listeners = new Set<() => void>()

function interpolate(text: string, params?: Params): string {
  if (!params) return text
  return text.replace(/\{(\w+)\}/g, (match, name: string) => (name in params ? String(params[name]) : match))
}

/** Translate `key` in `l` (defaults to the current language). */
export function translate(key: MessageKey, params?: Params, l: Lang = lang): string {
  return interpolate(DICTS[l][key] ?? DICTS.zh[key] ?? key, params)
}

export function hasMessage(key: string): key is MessageKey {
  return Object.hasOwn(DICTS.zh, key)
}

/** Translate a key built from server data (rule ids, fee names...), or return `fallback`. */
export function translateDynamic(key: string, fallback: string, params?: Params, l: Lang = lang): string {
  return hasMessage(key) ? translate(key, params, l) : fallback
}

function applyDocument() {
  if (typeof document === 'undefined') return
  document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en'
  document.title = translate('app.title')
}
applyDocument()

export function getLang(): Lang {
  return lang
}

export function setLang(next: Lang) {
  if (next === lang) return
  try {
    localStorage.setItem(STORAGE_KEY, next)
  } catch {
    // not persisted; still applied for this session
  }
  lang = next
  applyDocument()
  listeners.forEach((l) => l())
}

export function subscribeLang(cb: () => void): () => void {
  listeners.add(cb)
  return () => listeners.delete(cb)
}
