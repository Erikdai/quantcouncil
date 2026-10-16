import { Suspense } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import { BookOpenCheck, BookOpen, LayoutDashboard, MessagesSquare, Settings, Wallet, type LucideIcon } from 'lucide-react'
import { SkeletonRows } from '@/components/ui/Feedback'
import { Toaster } from '@/components/ui/Toaster'
import { useT } from '@/i18n/I18nProvider'
import type { MessageKey } from '@/i18n/store'
import { cn } from '@/lib/cn'
import { HealthIndicator } from './HealthIndicator'
import { LangToggle } from './LangToggle'
import { ThemeToggle } from './ThemeToggle'

interface NavItem {
  to: string
  label: MessageKey
  icon: LucideIcon
  /** Extra path prefixes that keep this item highlighted. */
  match?: string[]
}

const NAV: NavItem[] = [
  { to: '/', label: 'nav.dashboard', icon: LayoutDashboard, match: ['/runs'] },
  { to: '/portfolio', label: 'nav.portfolio', icon: Wallet },
  { to: '/deep-research', label: 'nav.deepResearch', icon: BookOpenCheck },
  { to: '/research', label: 'nav.research', icon: MessagesSquare },
  { to: '/skills', label: 'nav.skills', icon: BookOpen },
  { to: '/settings', label: 'nav.settings', icon: Settings },
]

function useIsActive() {
  const { pathname } = useLocation()
  return (item: NavItem) =>
    item.to === '/'
      ? pathname === '/' || (item.match ?? []).some((p) => pathname.startsWith(p))
      : pathname.startsWith(item.to)
}

function Brand() {
  const t = useT()
  return (
    <NavLink to="/" className="flex items-center gap-2.5">
      <img src="/favicon.svg" alt="" className="size-7" />
      <span className="leading-tight">
        <span className="block text-sm font-semibold tracking-tight text-fg">QuantCouncil</span>
        <span className="block text-[11px] text-muted">{t('app.subtitle')}</span>
      </span>
    </NavLink>
  )
}

/** Health, language and theme controls shown in both headers. */
function HeaderControls({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-1.5">
      <HealthIndicator compact={compact} />
      <LangToggle />
      <ThemeToggle />
    </div>
  )
}

function Sidebar() {
  const t = useT()
  const isActive = useIsActive()
  return (
    <aside className="sticky top-0 hidden h-dvh w-56 shrink-0 flex-col border-r border-line bg-surface lg:flex">
      <div className="flex h-14 items-center border-b border-line px-4">
        <Brand />
      </div>
      <nav className="flex-1 space-y-0.5 p-3" aria-label={t('nav.main')}>
        {NAV.map((item) => {
          const active = isActive(item)
          return (
            <NavLink
              key={item.to}
              to={item.to}
              aria-current={active ? 'page' : undefined}
              className={cn(
                'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition',
                active ? 'bg-accent/10 font-medium text-accent' : 'text-fg-2 hover:bg-surface-2 hover:text-fg',
              )}
            >
              <item.icon className="size-4" />
              {t(item.label)}
            </NavLink>
          )
        })}
      </nav>
      <p className="border-t border-line p-4 text-[11px] leading-relaxed text-muted">{t('app.disclaimer')}</p>
    </aside>
  )
}

function MobileTopBar() {
  const t = useT()
  const isActive = useIsActive()
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-surface/90 backdrop-blur lg:hidden">
      <div className="flex h-12 items-center justify-between gap-2 px-4">
        <Brand />
        <HeaderControls compact />
      </div>
      <nav className="flex gap-1 overflow-x-auto px-3 pb-2 [scrollbar-width:none]" aria-label={t('nav.main')}>
        {NAV.map((item) => {
          const active = isActive(item)
          return (
            <NavLink
              key={item.to}
              to={item.to}
              aria-current={active ? 'page' : undefined}
              className={cn(
                'flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-xs transition',
                active ? 'bg-accent text-accent-fg' : 'bg-surface-2 text-fg-2',
              )}
            >
              <item.icon className="size-3.5" />
              {t(item.label)}
            </NavLink>
          )
        })}
      </nav>
    </header>
  )
}

export function PageFallback() {
  return (
    <div className="space-y-4">
      <SkeletonRows rows={1} className="w-1/3" />
      <SkeletonRows rows={6} />
    </div>
  )
}

export function AppShell() {
  return (
    <div className="min-h-dvh lg:flex">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <MobileTopBar />
        <div className="sticky top-0 z-30 hidden h-14 items-center justify-end border-b border-line bg-bg/80 px-6 backdrop-blur lg:flex">
          <HeaderControls />
        </div>
        <main className="mx-auto w-full max-w-[1440px] flex-1 px-4 py-5 sm:px-6 sm:py-6">
          <Suspense fallback={<PageFallback />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
      <Toaster />
    </div>
  )
}
