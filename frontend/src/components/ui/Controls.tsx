import type { InputHTMLAttributes, ReactNode, Ref } from 'react'
import { cn } from '@/lib/cn'

// ---------------------------------------------------------------------------
// Tabs (controlled)
// ---------------------------------------------------------------------------

export interface TabItem<T extends string> {
  id: T
  label: ReactNode
  badge?: ReactNode
  disabled?: boolean
}

interface TabsProps<T extends string> {
  items: ReadonlyArray<TabItem<T>>
  value: T
  onChange: (id: T) => void
  className?: string
  ariaLabel?: string
}

export function Tabs<T extends string>({ items, value, onChange, className, ariaLabel }: TabsProps<T>) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn('flex gap-1 overflow-x-auto border-b border-line px-2 [scrollbar-width:none]', className)}
    >
      {items.map((t) => {
        const active = t.id === value
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={active}
            disabled={t.disabled}
            onClick={() => onChange(t.id)}
            className={cn(
              '-mb-px flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm whitespace-nowrap transition',
              active ? 'border-accent font-medium text-fg' : 'border-transparent text-muted hover:text-fg',
              t.disabled && 'cursor-not-allowed opacity-40',
            )}
          >
            {t.label}
            {t.badge}
          </button>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Segmented control
// ---------------------------------------------------------------------------

interface SegmentedProps<T extends string> {
  options: ReadonlyArray<{ value: T; label: ReactNode; title?: string }>
  value: T
  onChange: (v: T) => void
  className?: string
  size?: 'sm' | 'md'
}

export function Segmented<T extends string>({ options, value, onChange, className, size = 'sm' }: SegmentedProps<T>) {
  return (
    <div className={cn('inline-flex flex-wrap rounded-lg border border-line bg-surface-2 p-0.5', className)}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          title={o.title}
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={cn(
            'rounded-md whitespace-nowrap transition',
            size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3 py-1.5 text-sm',
            o.value === value ? 'bg-surface font-medium text-fg shadow-card' : 'text-muted hover:text-fg',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Switch
// ---------------------------------------------------------------------------

interface SwitchProps {
  checked: boolean
  onChange: (v: boolean) => void
  label: ReactNode
  description?: ReactNode
  id?: string
}

export function Switch({ checked, onChange, label, description, id }: SwitchProps) {
  return (
    <label htmlFor={id} className="flex cursor-pointer items-start gap-3 select-none">
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          'relative mt-0.5 inline-flex h-5 w-9 shrink-0 rounded-full transition',
          checked ? 'bg-accent' : 'bg-surface-3 ring-1 ring-line-strong ring-inset',
        )}
      >
        <span
          className={cn(
            'absolute top-0.5 size-4 rounded-full bg-white shadow transition-[left]',
            checked ? 'left-[18px]' : 'left-0.5',
          )}
        />
      </button>
      <span className="min-w-0">
        <span className="block text-sm text-fg">{label}</span>
        {description && <span className="block text-xs text-muted">{description}</span>}
      </span>
    </label>
  )
}

// ---------------------------------------------------------------------------
// Inputs
// ---------------------------------------------------------------------------

export const inputClass =
  'h-9 w-full rounded-lg border border-line bg-surface px-3 text-sm text-fg placeholder:text-muted/70 ' +
  'transition outline-none focus:border-accent focus:ring-2 focus:ring-accent/20 disabled:opacity-60'

export function Input({
  className,
  ref,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & { ref?: Ref<HTMLInputElement> }) {
  return <input ref={ref} className={cn(inputClass, className)} {...rest} />
}

export function Field({
  label,
  hint,
  error,
  htmlFor,
  children,
  className,
}: {
  label: ReactNode
  hint?: ReactNode
  error?: ReactNode
  htmlFor?: string
  children: ReactNode
  className?: string
}) {
  return (
    <div className={className}>
      <label htmlFor={htmlFor} className="mb-1.5 block text-xs font-medium text-fg-2">
        {label}
      </label>
      {children}
      {error ? (
        <p className="mt-1 text-xs text-up">{error}</p>
      ) : (
        hint && <p className="mt-1 text-xs text-muted">{hint}</p>
      )}
    </div>
  )
}
