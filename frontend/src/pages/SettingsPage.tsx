import { useId, useState } from 'react'
import { CircleCheck, CircleX, Cpu, Eye, EyeOff, KeyRound, Layers, PlugZap, Save } from 'lucide-react'
import {
  OUTPUT_LANGUAGES,
  type KeyStatus,
  type LLMProvider,
  type LLMSettings,
  type LLMSettingsIn,
  type LLMSettingsOut,
  type OutputLanguage,
  type ProviderInfo,
} from '@/api/types'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Field, Input, inputClass, Segmented, Switch } from '@/components/ui/Controls'
import { ErrorState, Skeleton } from '@/components/ui/Feedback'
import { useLlmCatalog, useLlmSettings, useSaveLlmSettings, useTestLlm } from '@/hooks/api'
import { useT } from '@/i18n/I18nProvider'
import type { MessageKey } from '@/i18n/store'
import { cn } from '@/lib/cn'
import { providerShort } from '@/lib/constants'
import { toast } from '@/lib/toast'

/** Editable form state: the settings plus the write-only key fields. */
interface FormState extends LLMSettings {
  apiKey: string
  clearKey: boolean
}

const CUSTOM = '__custom__'
const ROUNDS = ['1', '2', '3', '4', '5'] as const
const DEFAULT_TEMPERATURE = 0.7
const LANG_LABEL: Record<OutputLanguage, MessageKey> = {
  auto: 'settings.langAuto',
  'Simplified Chinese': 'settings.langZh',
  English: 'settings.langEn',
}

/** Catalog select with a "Custom…" option that reveals a free-text model id. */
function ModelField({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: string[]
  onChange: (v: string) => void
}) {
  const t = useT()
  const id = useId()
  const [custom, setCustom] = useState(() => !options.includes(value))
  return (
    <Field label={label} htmlFor={id} error={!value.trim() ? t('settings.modelRequired') : undefined}>
      <select
        id={id}
        value={custom ? CUSTOM : value}
        onChange={(e) => {
          if (e.target.value === CUSTOM) {
            setCustom(true)
          } else {
            setCustom(false)
            onChange(e.target.value)
          }
        }}
        className={cn(inputClass, 'font-mono')}
      >
        {options.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
        <option value={CUSTOM}>{t('settings.custom')}</option>
      </select>
      {custom && (
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={t('settings.customPlaceholder', { example: options[0] ?? 'model-id' })}
          className="mt-2 font-mono"
          spellCheck={false}
          autoComplete="off"
          aria-label={label}
        />
      )}
    </Field>
  )
}

/** Where the provider's key comes from, plus its masked hint, as shown under the key input. */
function KeyStatusText({ status }: { status: KeyStatus | undefined }) {
  const t = useT()
  if (!status?.set) return <span className="text-warn">{t('settings.keyNone')}</span>
  return (
    <span className="text-fg-2">
      {status.source === 'ui' ? t('settings.keyUi') : t('settings.keyEnv')}
      {status.hint && <span className="ml-1 font-mono">· {status.hint}</span>}
    </span>
  )
}

function SettingsForm({ initial, catalog }: { initial: LLMSettingsOut; catalog: ProviderInfo[] }) {
  const t = useT()
  const ids = { key: useId(), baseUrl: useId(), temp: useId() }
  const save = useSaveLlmSettings()
  const test = useTestLlm()
  const [showKey, setShowKey] = useState(false)
  const [form, setForm] = useState<FormState>(() => ({
    provider: initial.provider,
    quick_model: initial.quick_model,
    deep_model: initial.deep_model,
    base_url: initial.base_url,
    temperature: initial.temperature,
    max_debate_rounds: initial.max_debate_rounds,
    max_risk_rounds: initial.max_risk_rounds,
    output_language: initial.output_language,
    apiKey: '',
    clearKey: false,
  }))
  const set = (patch: Partial<FormState>) => setForm((f) => ({ ...f, ...patch }))

  const info = catalog.find((p) => p.id === form.provider)
  const keyStatus = initial.keys[form.provider]
  const newKey = form.apiKey.trim()
  const baseUrl = form.base_url?.trim() ?? ''
  const baseUrlError = baseUrl && !/^https?:\/\//i.test(baseUrl) ? t('settings.baseUrlInvalid') : undefined
  const invalid = !form.quick_model.trim() || !form.deep_model.trim() || !!baseUrlError

  // Switching provider preselects its first catalog models; a base URL or key belongs to the old provider.
  const changeProvider = (provider: LLMProvider) => {
    const next = catalog.find((p) => p.id === provider)
    set({
      provider,
      quick_model: next?.quick_models[0] ?? '',
      deep_model: next?.deep_models[0] ?? '',
      base_url: null,
      apiKey: '',
      clearKey: false,
    })
    test.reset()
  }

  const payload = (): LLMSettingsIn => ({
    provider: form.provider,
    quick_model: form.quick_model.trim(),
    deep_model: form.deep_model.trim(),
    base_url: baseUrl || null,
    temperature: form.temperature,
    max_debate_rounds: form.max_debate_rounds,
    max_risk_rounds: form.max_risk_rounds,
    output_language: form.output_language,
    api_key: newKey || null,
    // A newly typed key replaces the saved one; "clear" only applies without one.
    clear_key: form.clearKey && !newKey,
  })

  const onSave = () =>
    save.mutate(payload(), {
      onSuccess: (saved) =>
        toast.success(
          t('settings.saved'),
          t('settings.savedDesc', { provider: providerShort(saved.provider), model: saved.deep_model }),
        ),
    })

  const result = test.data

  return (
    <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-2">
      <div className="min-w-0 space-y-5">
        <Card>
          <CardHeader title={t('settings.providerTitle')} icon={<Cpu />} subtitle={t('settings.providerSubtitle')} />
          <CardBody className="space-y-4">
            <Segmented
              size="md"
              options={catalog.map((p) => ({ value: p.id, label: p.label }))}
              value={form.provider}
              onChange={changeProvider}
            />

            <Field
              label={t('settings.apiKey')}
              htmlFor={ids.key}
              hint={
                <span className="inline-flex flex-wrap items-center gap-x-2">
                  <KeyRound className="size-3" aria-hidden />
                  {newKey ? (
                    <span className="text-accent">{t('settings.keyWillReplace')}</span>
                  ) : form.clearKey ? (
                    <>
                      <span className="text-warn">{t('settings.keyWillClear')}</span>
                      <button type="button" className="text-accent hover:underline" onClick={() => set({ clearKey: false })}>
                        {t('settings.undo')}
                      </button>
                    </>
                  ) : (
                    <>
                      <KeyStatusText status={keyStatus} />
                      {keyStatus?.source === 'ui' && (
                        <button type="button" className="text-up hover:underline" onClick={() => set({ clearKey: true })}>
                          {t('settings.keyClear')}
                        </button>
                      )}
                    </>
                  )}
                </span>
              }
            >
              <div className="relative">
                <Input
                  id={ids.key}
                  type={showKey ? 'text' : 'password'}
                  value={form.apiKey}
                  onChange={(e) => set({ apiKey: e.target.value })}
                  placeholder={
                    keyStatus?.set
                      ? t('settings.keyPlaceholderReplace')
                      : t('settings.keyPlaceholderNew', { provider: info?.label ?? form.provider })
                  }
                  autoComplete="new-password"
                  spellCheck={false}
                  className="pr-9 font-mono"
                />
                <button
                  type="button"
                  onClick={() => setShowKey((v) => !v)}
                  aria-label={showKey ? t('settings.hideKey') : t('settings.showKey')}
                  className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-1 text-muted hover:text-fg"
                >
                  {showKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>
            </Field>

            <Field
              label={t('settings.baseUrl')}
              htmlFor={ids.baseUrl}
              hint={t('settings.baseUrlHint')}
              error={baseUrlError}
            >
              <Input
                id={ids.baseUrl}
                value={form.base_url ?? ''}
                onChange={(e) => set({ base_url: e.target.value || null })}
                placeholder={t('settings.baseUrlPlaceholder')}
                spellCheck={false}
                autoComplete="off"
                className="font-mono"
              />
            </Field>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title={t('settings.modelsTitle')} icon={<Layers />} subtitle={t('settings.modelsSubtitle')} />
          {/* Keyed by provider so the custom-model toggles reset with the preselected models. */}
          <CardBody key={form.provider} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <ModelField
              label={t('settings.quickModel')}
              value={form.quick_model}
              options={info?.quick_models ?? []}
              onChange={(v) => set({ quick_model: v })}
            />
            <ModelField
              label={t('settings.deepModel')}
              value={form.deep_model}
              options={info?.deep_models ?? []}
              onChange={(v) => set({ deep_model: v })}
            />
          </CardBody>
        </Card>
      </div>

      <div className="min-w-0 space-y-5">
        <Card>
          <CardHeader title={t('settings.depthTitle')} icon={<Layers />} subtitle={t('settings.depthSubtitle')} />
          <CardBody className="space-y-5">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label={t('settings.debateRounds')}>
                <Segmented
                  options={ROUNDS.map((r) => ({ value: r, label: r }))}
                  value={String(form.max_debate_rounds) as (typeof ROUNDS)[number]}
                  onChange={(v) => set({ max_debate_rounds: Number(v) })}
                />
              </Field>
              <Field label={t('settings.riskRounds')}>
                <Segmented
                  options={ROUNDS.map((r) => ({ value: r, label: r }))}
                  value={String(form.max_risk_rounds) as (typeof ROUNDS)[number]}
                  onChange={(v) => set({ max_risk_rounds: Number(v) })}
                />
              </Field>
            </div>

            <Field label={t('settings.temperature')} htmlFor={ids.temp}>
              <div className="flex items-center gap-3">
                <input
                  id={ids.temp}
                  type="range"
                  min={0}
                  max={2}
                  step={0.05}
                  value={form.temperature ?? DEFAULT_TEMPERATURE}
                  disabled={form.temperature === null}
                  onChange={(e) => set({ temperature: Number(e.target.value) })}
                  className="h-2 w-full cursor-pointer accent-accent disabled:cursor-not-allowed disabled:opacity-40"
                />
                <span className="w-10 text-right font-mono text-sm text-fg tabular-nums">
                  {form.temperature === null ? '—' : form.temperature.toFixed(2)}
                </span>
              </div>
              <div className="mt-2">
                <Switch
                  checked={form.temperature === null}
                  onChange={(useDefault) => set({ temperature: useDefault ? null : DEFAULT_TEMPERATURE })}
                  label={t('settings.temperatureDefault')}
                />
              </div>
            </Field>

            <Field label={t('settings.language')} hint={t('settings.langHint')}>
              <Segmented
                options={OUTPUT_LANGUAGES.map((l) => ({ value: l, label: t(LANG_LABEL[l]) }))}
                value={form.output_language}
                onChange={(v) => set({ output_language: v })}
              />
            </Field>
          </CardBody>
        </Card>

        <Card>
          <CardBody className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Button
                icon={<PlugZap className="size-4" />}
                loading={test.isPending}
                disabled={invalid}
                onClick={() => test.mutate(payload())}
              >
                {t('settings.test')}
              </Button>
              <Button
                variant="primary"
                icon={<Save className="size-4" />}
                loading={save.isPending}
                disabled={invalid}
                onClick={onSave}
              >
                {t('settings.save')}
              </Button>
              <span className="text-xs text-muted">{t('settings.testHint')}</span>
            </div>

            {result && (
              <div
                role="status"
                className={cn(
                  'flex gap-2.5 rounded-lg border p-3 text-sm',
                  result.ok ? 'border-ok/30 bg-ok/[0.06]' : 'border-up/30 bg-up/[0.06]',
                )}
              >
                {result.ok ? (
                  <CircleCheck className="mt-0.5 size-4 shrink-0 text-ok" />
                ) : (
                  <CircleX className="mt-0.5 size-4 shrink-0 text-up" />
                )}
                <div className="min-w-0 space-y-0.5">
                  <p className="font-medium text-fg">
                    {result.ok ? t('settings.testOk') : t('settings.testFailed')}
                    <span className="ml-2 font-mono text-xs font-normal text-muted">
                      {result.model}
                      {result.latency_ms != null && ` · ${result.latency_ms} ms`}
                    </span>
                  </p>
                  {/* the reply / error comes from the provider and is shown as-is */}
                  {result.ok && result.reply && (
                    <p className="text-xs text-fg-2">{t('settings.testReply', { reply: result.reply })}</p>
                  )}
                  {!result.ok && result.error && <p className="font-mono text-xs break-words text-up">{result.error}</p>}
                </div>
              </div>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  )
}

export default function SettingsPage() {
  const t = useT()
  const settings = useLlmSettings()
  const catalog = useLlmCatalog()

  return (
    <>
      <PageHeader title={t('settings.title')} description={t('settings.desc')} />
      {settings.isPending || catalog.isPending ? (
        <div className="grid gap-5 lg:grid-cols-2">
          <Skeleton className="h-[420px] rounded-xl" />
          <Skeleton className="h-[420px] rounded-xl" />
        </div>
      ) : settings.isError || catalog.isError ? (
        <Card>
          <ErrorState
            error={settings.error ?? catalog.error}
            onRetry={() => {
              void settings.refetch()
              void catalog.refetch()
            }}
          />
        </Card>
      ) : (
        // Remount with the server's values after every save (clears the typed key).
        <SettingsForm key={settings.dataUpdatedAt} initial={settings.data} catalog={catalog.data} />
      )}
    </>
  )
}
