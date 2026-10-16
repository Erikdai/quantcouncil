import { lazy } from 'react'
import { createBrowserRouter, isRouteErrorResponse, Link, useRouteError } from 'react-router'
import { AppShell } from '@/components/layout/AppShell'
import { Button, buttonClass } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/Feedback'
import { useT } from '@/i18n/I18nProvider'

// Route-level code splitting: charts and Markdown only load where needed.
const DashboardPage = lazy(() => import('@/pages/DashboardPage'))
const RunPage = lazy(() => import('@/pages/RunPage'))
const PortfolioPage = lazy(() => import('@/pages/PortfolioPage'))
const DeepResearchPage = lazy(() => import('@/pages/DeepResearchPage'))
const ResearchPage = lazy(() => import('@/pages/ResearchPage'))
const SkillsPage = lazy(() => import('@/pages/SkillsPage'))
const SettingsPage = lazy(() => import('@/pages/SettingsPage'))

function NotFound() {
  const t = useT()
  return (
    <EmptyState
      title={t('notFound.title')}
      description={t('notFound.desc')}
      action={
        <Link to="/" className={buttonClass('primary')}>
          {t('notFound.back')}
        </Link>
      }
    />
  )
}

function RouteError() {
  const t = useT()
  const err = useRouteError()
  const message = isRouteErrorResponse(err)
    ? `${err.status} ${err.statusText}`
    : err instanceof Error
      ? err.message
      : t('error.unknown')
  return (
    <div className="flex min-h-dvh items-center justify-center p-6">
      <EmptyState
        title={t('error.page')}
        description={message}
        action={
          <Button variant="primary" onClick={() => window.location.assign('/')}>
            {t('error.reload')}
          </Button>
        }
      />
    </div>
  )
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'runs/:id', element: <RunPage /> },
      { path: 'portfolio', element: <PortfolioPage /> },
      { path: 'research', element: <ResearchPage /> },
      { path: 'deep-research', element: <DeepResearchPage /> },
      { path: 'deep-research/:id', element: <DeepResearchPage /> },
      { path: 'skills', element: <SkillsPage /> },
      { path: 'skills/:name', element: <SkillsPage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: '*', element: <NotFound /> },
    ],
  },
])
