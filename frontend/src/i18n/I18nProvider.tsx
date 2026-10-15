import { createContext, useContext, useMemo, useSyncExternalStore, type ReactNode } from 'react'
import {
  getLang,
  setLang,
  subscribeLang,
  translate,
  translateDynamic,
  type Lang,
  type MessageKey,
  type Params,
} from './store'

export type TFunction = (key: MessageKey, params?: Params) => string

export interface I18nValue {
  lang: Lang
  setLang: (lang: Lang) => void
  /** Typed lookup: unknown keys are compile errors. */
  t: TFunction
  /** Lookup for keys derived from server data; returns `fallback` when missing. */
  tx: (key: string, fallback: string, params?: Params) => string
}

const I18nContext = createContext<I18nValue | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  const lang = useSyncExternalStore(subscribeLang, getLang)
  const value = useMemo<I18nValue>(
    () => ({
      lang,
      setLang,
      t: (key, params) => translate(key, params, lang),
      tx: (key, fallback, params) => translateDynamic(key, fallback, params, lang),
    }),
    [lang],
  )
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext)
  if (!value) throw new Error('useI18n must be used inside <I18nProvider>')
  return value
}

export function useT(): TFunction {
  return useI18n().t
}
