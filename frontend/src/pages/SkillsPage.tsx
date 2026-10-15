import { Link, useParams } from 'react-router'
import { ArrowLeft, BookOpen, ChevronRight, Puzzle } from 'lucide-react'
import { Markdown } from '@/components/common/Markdown'
import { PageHeader } from '@/components/layout/PageHeader'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { EmptyState, ErrorState, Skeleton, SkeletonRows } from '@/components/ui/Feedback'
import { useSkill, useSkills } from '@/hooks/api'
import { useT } from '@/i18n/I18nProvider'
import { cn } from '@/lib/cn'

/** Drop a leading YAML front-matter block (name / description are shown separately). */
function stripFrontMatter(md: string): string {
  return md.replace(/^﻿?---\r?\n[\s\S]*?\r?\n---\r?\n?/, '')
}

function SkillList({ active }: { active: string | undefined }) {
  const t = useT()
  const { data, isPending, isError, error, refetch } = useSkills()
  return (
    <Card className={cn('min-w-0', active && 'hidden lg:block')}>
      <CardHeader
        title="Agent Skills"
        icon={<Puzzle />}
        subtitle={data ? t('skills.count', { n: data.length }) : undefined}
      />
      {isPending ? (
        <SkeletonRows rows={5} className="p-4" />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : data.length === 0 ? (
        <EmptyState icon={<Puzzle />} title={t('skills.emptyTitle')} description={t('skills.emptyDesc')} />
      ) : (
        <ul className="divide-y divide-line">
          {data.map((s) => (
            <li key={s.name}>
              <Link
                to={`/skills/${encodeURIComponent(s.name)}`}
                aria-current={s.name === active ? 'page' : undefined}
                className={cn(
                  'flex items-start gap-3 px-4 py-3 transition',
                  s.name === active ? 'bg-accent/[0.07]' : 'hover:bg-surface-2',
                )}
              >
                <div className="min-w-0 flex-1">
                  <p className={cn('font-mono text-[13px] font-medium', s.name === active ? 'text-accent' : 'text-fg')}>
                    {s.name}
                  </p>
                  {/* skill descriptions come from SKILL.md and are shown as-is */}
                  <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-muted">{s.description}</p>
                </div>
                <ChevronRight className="mt-1 size-4 shrink-0 text-muted" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function SkillDetail({ name }: { name: string }) {
  const t = useT()
  const { data, isPending, isError, error, refetch } = useSkill(name)
  return (
    <Card className="min-w-0">
      <div className="border-b border-line px-4 py-3 lg:hidden">
        <Link to="/skills" className="inline-flex items-center gap-1 text-xs text-muted hover:text-accent">
          <ArrowLeft className="size-3.5" /> {t('skills.back')}
        </Link>
      </div>
      {isPending ? (
        <div className="space-y-3 p-5">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-4 w-3/4" />
          <SkeletonRows rows={6} />
        </div>
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <>
          <CardHeader title={<span className="font-mono">{data.name}</span>} icon={<BookOpen />} subtitle="SKILL.md" />
          <CardBody className="space-y-4 sm:p-6">
            <p className="rounded-lg border-l-4 border-accent bg-accent/[0.05] px-3 py-2 text-sm text-fg-2">
              {data.description}
            </p>
            {data.body ? (
              <Markdown>{stripFrontMatter(data.body)}</Markdown>
            ) : (
              <p className="text-sm text-muted">{t('skills.noBody')}</p>
            )}
          </CardBody>
        </>
      )}
    </Card>
  )
}

export default function SkillsPage() {
  const t = useT()
  const { name } = useParams()
  return (
    <>
      <PageHeader title={t('skills.title')} description={t('skills.desc')} />
      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        <SkillList active={name} />
        {name ? (
          <SkillDetail name={name} />
        ) : (
          <Card className="hidden lg:block">
            <EmptyState
              icon={<BookOpen />}
              title={t('skills.pickTitle')}
              description={t('skills.pickDesc')}
              className="py-20"
            />
          </Card>
        )}
      </div>
    </>
  )
}
