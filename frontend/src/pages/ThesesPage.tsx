import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { theses, busy, type Candidate, type Rule, type ThesisReview, type ThesisVersion } from '@/api/theses'
import { deepResearch, type ResearchEvidence } from '@/api/deepResearch'
import { PageHeader } from '@/components/layout/PageHeader'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Field, Input } from '@/components/ui/Controls'
import { ErrorState } from '@/components/ui/Feedback'
import { useI18n } from '@/i18n/I18nProvider'
import { toISODate } from '@/lib/format'

const metrics = ['revenue', 'operating_income', 'net_income', 'operating_cash_flow', 'capex', 'repurchases', 'dividends', 'operating_margin', 'free_cash_flow']
const zh: Record<string, string> = {
  trend: '趋势：最近 N 次披露同比增加', threshold: '阈值：指标达到设定条件', relative: '比较：分部为最大单一增量贡献者', coverage: '覆盖：经营现金流覆盖现金支出',
  revenue: '营业收入', operating_income: '营业利润（GAAP）', net_income: '净利润', operating_cash_flow: '经营现金流', capex: '现金资产采购额（毛额，不含非现金租赁）', repurchases: '现金回购', dividends: '现金分红', operating_margin: '营业利润率', free_cash_flow: '经营现金流减现金资产采购额',
  quantitative: '定量候选，尚需检查', qualitative: '定性观点，需人工核验', not_verifiable: '暂不可验证', direct: '直接检验', partial: '仅部分条件', proxy: '仅代理指标', new_hypothesis: '新假设或未来改写',
  supported: '已定义条件获支持', contradicted: '已定义条件被反证', insufficient: '证据不足', unknown: '尚未检查', pending: '待获取当前证据', fresh: '本次数据检查成功', historical: '历史截止日验证', stale: '监控检查已过期', partial_data: '资料不完整或待复核',
  draft: '待确认', active: '自动追踪中', paused: '仅手动复查', archived: '已归档', queued: '排队中', running: '检查中', completed: '检查完成', failed: '任务失败', needs_review: '需复核，不能自动启用', unchanged: '无新相关证据，未重新调用模型', baseline: '基准验证', manual: '手动复查', scheduled: '自动复查',
}
function useWords() {
  const { lang } = useI18n()
  const text = (cn: string, en: string) => lang === 'zh' ? cn : en
  const label = (key?: string | null) => key ? (lang === 'zh' ? zh[key] ?? key : key.replaceAll('_', ' ')) : text('尚无判断', 'No assessment')
  return { text, label }
}
function initialRule(template: Rule['template']): Rule {
  return { template, metric: template === 'relative' ? 'operating_income' : template === 'threshold' ? 'operating_margin' : 'operating_cash_flow', period: 'annual', operator: 'gt', threshold: null, observations: 1, target_segment: null, coverage_expectation: 'covers', cash_outflows: ['capex'] }
}
const selectClass = 'w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm'
const areaClass = 'min-h-24 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm leading-6'
const segmentName = (s: string) => s.split(':').pop()?.replace(/SegmentMember$|Member$/g, '').replace(/([a-z])([A-Z])/g, '$1 $2') ?? s

function RuleEditor({ rule, onChange, segments }: { rule: Rule | null; onChange: (r: Rule | null) => void; segments: string[] }) {
  const { text, label } = useWords()
  return <div className="space-y-3">
    <Field label={text('验证模板', 'Verification template')}><select aria-label={text('验证模板', 'Verification template')} className={selectClass} value={rule?.template ?? 'none'} onChange={e => onChange(e.target.value === 'none' ? null : initialRule(e.target.value as Rule['template']))}>
      <option value="none">{text('仅保存，不自动判断', 'Save without automatic judgment')}</option>{(['trend', 'threshold', 'relative', 'coverage'] as const).map(t => <option key={t} value={t}>{label(t)}</option>)}
    </select></Field>
    {rule && <>
      <Field label={text('比较期间', 'Period policy')}><select aria-label={text('比较期间', 'Period policy')} className={selectClass} value={rule.period} onChange={e => onChange({ ...rule, period: e.target.value as Rule['period'] })}><option value="annual">{text('仅年度同比', 'Annual year-on-year only')}</option><option value="latest_reported">{text('最新披露累计期间，与上年同期间比较', 'Latest reported cumulative period versus prior-year equivalent')}</option></select></Field>
      {(rule.template === 'trend' || rule.template === 'threshold') && <Field label={text('指标', 'Metric')}><select aria-label={text('指标', 'Metric')} className={selectClass} value={rule.metric} onChange={e => onChange({ ...rule, metric: e.target.value })}>{metrics.map(m => <option key={m} value={m}>{label(m)}</option>)}</select></Field>}
      {rule.template === 'trend' && <Field label={text('连续披露次数（不是自动推断的季度数）', 'Number of consecutive disclosures')}><Input aria-label={text('连续披露次数', 'Number of disclosures')} type="number" min={1} max={3} value={rule.observations} onChange={e => onChange({ ...rule, observations: Number(e.target.value) })} /></Field>}
      {rule.template === 'threshold' && <div className="grid grid-cols-2 gap-3"><Field label={text('比较方式', 'Comparison')}><select aria-label={text('比较方式', 'Comparison')} className={selectClass} value={rule.operator} onChange={e => onChange({ ...rule, operator: e.target.value as Rule['operator'] })}>{Object.entries({ gt: '>', gte: '≥', lt: '<', lte: '≤' }).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field><Field label={text('阈值', 'Threshold') + (rule.metric === 'operating_margin' ? ' (%)' : ' (USD million)')}><Input aria-label={text('阈值', 'Threshold')} type="number" step="any" value={rule.threshold ?? ''} onChange={e => onChange({ ...rule, threshold: e.target.value })} /></Field></div>}
      {rule.template === 'relative' && <><Field label={text('目标分部', 'Target segment')}><select aria-label={text('目标分部', 'Target segment')} className={selectClass} value={rule.target_segment ?? ''} onChange={e => onChange({ ...rule, target_segment: e.target.value || null })}><option value="">{text('请选择分部', 'Choose a segment')}</option>{[...new Set([...segments, ...(rule.target_segment ? [rule.target_segment] : [])])].map(s => <option key={s} value={s}>{segmentName(s)}</option>)}</select></Field><p className="text-xs leading-6 text-muted">{text('固定条件：集团利润增量为正、目标分部增量为正，并严格大于每一个其他分部；并列不满足。“超过一半”不在这条规则中。比较集合必须完整且跨期一致。', 'Fixed: positive group and target changes; target strictly exceeds every other segment. Ties fail. Majority share is a different claim. The complete peer roster must remain comparable.')}</p></>}
      {rule.template === 'coverage' && <Field label={text('需要覆盖的现金支出', 'Cash outflows to cover')}><div className="space-y-2"><select aria-label={text('覆盖方向', 'Coverage expectation')} className={selectClass} value={rule.coverage_expectation ?? 'covers'} onChange={e => onChange({ ...rule, coverage_expectation: e.target.value as Rule['coverage_expectation'] })}><option value="covers">{text('能够覆盖（现金流 ≥ 支出）', 'Covers: cashflow ≥ outflows')}</option><option value="shortfall">{text('存在缺口（现金流 < 支出）', 'Shortfall: cashflow < outflows')}</option></select>{['capex', 'repurchases', 'dividends'].map(m => <label className="flex gap-2 text-sm" key={m}><input type="checkbox" checked={rule.cash_outflows.includes(m)} onChange={e => onChange({ ...rule, cash_outflows: e.target.checked ? [...rule.cash_outflows, m] : rule.cash_outflows.filter(v => v !== m) })} />{label(m)}</label>)}</div></Field>}
      <p className="text-xs text-muted">{text('金额单位：百万美元；期限：持续至用户暂停。更改指标、阈值或期间后，必须重新验证并创建版本。', 'Amounts: USD million. Runs until paused. Changed metrics, thresholds or periods require a new verified version.')}</p>
    </>}
  </div>
}
function CandidateCard({ candidate, index, extractionId, segments }: { candidate: Candidate; index: number; extractionId: string; segments: string[] }) {
  const { text, label } = useWords()
  const [statement, setStatement] = useState(candidate.statement)
  const [rule, setRule] = useState(candidate.rule)
  const navigate = useNavigate()
  const create = useMutation({ mutationFn: () => theses.create({ extraction_id: extractionId, candidate_index: index, statement, rule, horizon: 'until_paused' }), onSuccess: d => navigate(`/theses/${d.thesis_id}`) })
  return <Card><CardHeader title={`${label(candidate.verification_class)} · ${label(candidate.relationship)}`} /><CardBody className="space-y-4">
    <blockquote className="border-l-2 border-line pl-3 text-sm leading-7 text-muted">{text('原文：', 'Original: ')}{candidate.original_text}</blockquote>
    <Field label={text('准备检验的独立观点', 'Exact hypothesis to test')}><textarea aria-label={text('准备检验的独立观点', 'Exact hypothesis to test')} className={areaClass} value={statement} onChange={e => setStatement(e.target.value)} /></Field>
    {[...candidate.suggested_assumptions, ...candidate.limitations, ...candidate.extraction_errors].map((s, i) => <p key={i} className="text-xs leading-6 text-warn">{s}</p>)}
    <RuleEditor rule={rule} onChange={setRule} segments={segments} />
    <Button variant="primary" loading={create.isPending} onClick={() => create.mutate()} disabled={statement.trim().length < 10}>{rule ? text('检查可追踪性和基准证据', 'Check meaning and baseline') : text('仅保存观点', 'Save belief only')}</Button>
    {create.isError && <p role="alert" className="text-sm text-warn">{create.error.message}</p>}
  </CardBody></Card>
}
function EvidenceList({ sources }: { sources: ResearchEvidence[] }) {
  const { text } = useWords()
  return <details className="mt-3 text-xs"><summary className="cursor-pointer text-accent">{text('原始证据与计算输入', 'Original evidence and calculation inputs')} ({sources.length})</summary><div className="mt-3 space-y-3">{sources.map(s => <div className="rounded border border-line p-3" key={s.id}><a href={s.url} target="_blank" rel="noreferrer" className="text-accent underline">{s.title}</a><p>{text('披露：', 'Filed: ')}{s.filed}</p><p className="mt-1 break-words leading-6">{s.content}</p>{s.sha256 && <p className="break-all text-muted">SHA-256 {s.sha256}</p>}</div>)}</div></details>
}
function ReviewCard({ review, onRead }: { review: ThesisReview; onRead: () => void }) {
  const { text, label } = useWords()
  return <div className="border-t border-line py-4">
    <div className="flex flex-wrap items-center gap-3"><strong className="text-sm">{review.as_of} · {label(review.kind)}</strong><span className="text-xs text-muted">{label(review.status)}</span>{review.unread && <Button onClick={onRead}>{text('新变化 · 标记已读', 'New change · Mark read')}</Button>}</div>
    {review.error && <p className="mt-2 text-xs text-warn">{review.error}</p>}
    {review.result && <><p className="mt-2 text-sm">{text('数值条件计算：', 'Numerical conditions: ')}{label(review.result.judgment)}</p>{(busy(review.status) || !review.result.eligible) && <p className="text-xs text-warn">{text('尚未通过完整可追踪性检查，不能据此启用自动判断。', 'Full trackability has not passed; this is not an accepted assessment.')}</p>}<p className="mt-1 text-xs leading-6 text-muted">{review.result.reason}</p>{review.result.eligibility_errors?.map((e, i) => <p key={i} className="mt-1 text-xs text-warn">{e}</p>)}
      {review.result.checks.map((c, i) => <div key={i} className="mt-3 rounded border border-line p-3 text-xs leading-6"><strong>{String(c.start)} → {String(c.end)} · {c.passed ? text('条件满足', 'Condition holds') : text('条件不满足', 'Condition fails')}</strong>{Object.entries(c).filter(([k]) => !['start', 'end', 'passed'].includes(k)).map(([k, v]) => <p key={k} className="break-words">{k.endsWith('_usd') ? k.replace('_usd', ' (USD million)') : k}: {typeof v === 'object' ? JSON.stringify(k.endsWith('_usd') && v ? Object.fromEntries(Object.entries(v).map(([name, amount]) => [segmentName(name), Number(amount) / 1e6])) : v) : k.endsWith('_usd') ? (Number(v) / 1e6).toLocaleString() : String(v)}</p>)}</div>)}
      {review.result.scope_review && <p className="mt-2 text-xs leading-6 text-muted">{review.result.scope_review.explanation}</p>}<EvidenceList sources={review.result.sources ?? []} />
    </>}
    {review.snapshot && <p className="mt-2 text-[11px] text-muted">{text('实际取数时间：', 'Actual fetch: ')}{review.snapshot.fetched_at} · {text('最新文件披露：', 'Newest filing: ')}{review.snapshot.manifest.map(f => f.filed).sort().at(-1)}</p>}
  </div>
}
function VersionPanel({ version, baseline, segments, thesisId, onRefresh, latest }: { latest: boolean; version: ThesisVersion; baseline?: ThesisReview; segments: string[]; thesisId: string; onRefresh: () => void }) {
  const { text, label } = useWords()
  const [statement, setStatement] = useState(version.statement)
  const [rule, setRule] = useState(version.rule)
  const [ack, setAck] = useState(false)
  const [reformulation, setReformulation] = useState(false)
  const [auto, setAuto] = useState(false)
  const revise = useMutation({ mutationFn: () => theses.revise(thesisId, { statement, rule, horizon: 'until_paused' }), onSuccess: onRefresh })
  const confirm = useMutation({ mutationFn: () => theses.confirm(thesisId, { version_id: version.id, contract_hash: version.contract_hash, acknowledge_baseline: true, accept_reformulation: reformulation, start_monitoring: auto }), onSuccess: onRefresh })
  return <Card><CardHeader title={`v${version.number} · ${version.confirmed_at ? text('已确认，规则锁定', 'Confirmed, locked') : text('待确认', 'Awaiting confirmation')}`} /><CardBody className="space-y-4">
    <p className="text-sm leading-7">{version.statement}</p><div className="rounded border border-line p-3 text-xs leading-6"><strong>{text('本版本的实际规则', 'Exact rule for this version')}</strong><p>{version.rule ? `${label(version.rule.template)} · ${label(version.rule.metric)} · ${version.rule.period === 'annual' ? text('年度同比', 'Annual') : text('最新累计披露同比', 'Latest cumulative disclosure')}` : text('仅保存，不自动判断', 'Save only')}</p>{version.rule?.template === 'threshold' && <p>{version.rule.operator} {version.rule.threshold} {version.rule.metric === 'operating_margin' ? '%' : 'USD million'}</p>}{version.rule?.template === 'trend' && <p>{text('连续披露次数：', 'Consecutive disclosures: ')}{version.rule.observations}</p>}{version.rule?.template === 'relative' && <p>{segmentName(version.rule.target_segment ?? '')} · {text('唯一最大单一增量；不等于超过一半；并列不满足', 'Unique largest contributor; not majority; ties fail')}</p>}{version.rule?.template === 'coverage' && <p>{version.rule.coverage_expectation === 'shortfall' ? text('存在现金缺口', 'Cash shortfall') : text('现金流能够覆盖', 'Cashflow covers')} · {version.rule.cash_outflows.map(label).join(' + ')}</p>}<p>{text('持续至用户暂停', 'Until paused by the user')}</p></div><Link to={`/deep-research/${version.origin.source_job_id}`} className="text-xs text-accent underline">{text('查看原始报告及原文', 'Original research')}</Link><blockquote className="border-l-2 border-line pl-3 text-xs leading-6 text-muted">{version.origin.original_text}</blockquote>
    {!version.origin.source_checks_passed && <p className="text-xs text-warn">{text('原报告未通过全部检查；不能把其完成状态当作事实证明。', 'The original report did not pass all checks.')}</p>}
    {version.meaning_review && <div className="rounded border border-line p-3 text-xs leading-6"><strong>{text('原意关系：', 'Relationship: ')}{label(version.meaning_review.relationship)}</strong><p>{version.meaning_review.explanation}</p>{[...version.meaning_review.issues, ...version.meaning_review.assumptions].map((s, i) => <p key={i} className="text-warn">{s}</p>)}</div>}
    {baseline && <ReviewCard review={baseline} onRead={() => {}} />}
    {latest && !version.confirmed_at && <div className="space-y-3 border-t border-line pt-4">
      <p className="text-xs leading-6 text-muted">{text('确认只锁定这条具体假设。代理指标、部分条件或新假设通过，不代表原来的综合投资观点成立。', 'Confirmation applies only to this hypothesis. A proxy/child condition does not prove the broader original belief.')}</p>
      <label className="flex gap-2 text-xs leading-6"><input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)} />{text('我已阅读这版规则和基准结果，包括不满足的条件', 'I reviewed this exact rule and baseline, including failing conditions')}</label>
      <label className="flex gap-2 text-xs leading-6"><input type="checkbox" checked={reformulation} onChange={e => setReformulation(e.target.checked)} />{text('我明确接受缩小、代理或新假设，以及建议的阈值/观察期；不将其等同于原观点', 'I explicitly accept any narrowing, proxy, new hypothesis or suggested parameters')}</label>
      <label className="flex gap-2 text-xs leading-6"><input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} />{text('开启每日自动检查；否则仅手动复查', 'Enable daily checks; otherwise review manually')}</label>
      <Button variant="primary" loading={confirm.isPending} disabled={!ack || baseline?.status !== 'completed' || !baseline.result?.eligible} onClick={() => confirm.mutate()}>{text('确认并锁定此版本', 'Confirm and lock this version')}</Button>
      {confirm.isError && <p role="alert" className="text-xs text-warn">{confirm.error.message}</p>}
    </div>}
    {latest && <details><summary className="cursor-pointer text-xs text-accent">{text('修改观点或规则：创建新版本', 'Change hypothesis or rule: create a new version')}</summary><div className="mt-4 space-y-4"><textarea aria-label={text('新版本观点', 'New version statement')} className={areaClass} value={statement} onChange={e => setStatement(e.target.value)} /><RuleEditor rule={rule} onChange={setRule} segments={segments} /><Button loading={revise.isPending} onClick={() => revise.mutate()}>{text('创建新版本并重新检查', 'Create and verify new version')}</Button>{revise.isError && <p role="alert" className="text-xs text-warn">{revise.error.message}</p>}</div></details>}
    <details className="text-[11px] text-muted"><summary>{text('版本校验值', 'Contract fingerprint')}</summary><p className="break-all">{version.contract_hash}</p></details>
  </CardBody></Card>
}
export default function ThesesPage() {
  const { text, label } = useWords()
  const { id } = useParams()
  const [params, setParams] = useSearchParams()
  const [sourceId, setSourceId] = useState(params.get('research') ?? '')
  const extractionId = params.get('extraction')
  const [asOf, setAsOf] = useState('')
  const client = useQueryClient()
  const history = useQuery({ queryKey: ['theses'], queryFn: theses.list, refetchInterval: 6000 })
  const reports = useQuery({ queryKey: ['deep-research'], queryFn: () => deepResearch.list() })
  const detail = useQuery({ queryKey: ['theses', id], queryFn: () => theses.get(id!), enabled: Boolean(id), refetchInterval: q => q.state.data?.reviews.some(r => busy(r.status)) ? 2500 : false })
  const extraction = useQuery({ queryKey: ['thesis-extraction', extractionId], queryFn: () => theses.extraction(extractionId!), enabled: Boolean(extractionId), refetchInterval: q => busy(q.state.data?.status) ? 2500 : false })
  const originalId = extraction.data?.source_job_id
  const original = useQuery({ queryKey: ['deep-research', originalId], queryFn: () => deepResearch.get(originalId!), enabled: Boolean(originalId) })
  const extract = useMutation({ mutationFn: () => theses.extract(sourceId), onSuccess: d => setParams({ extraction: d.id }) })
  const refresh = () => { void detail.refetch(); void client.invalidateQueries({ queryKey: ['theses'] }) }
  const check = useMutation({ mutationFn: () => theses.check(id!, asOf || null), onSuccess: refresh })
  const lifecycle = useMutation({ mutationFn: (v: string) => theses.lifecycle(id!, v), onSuccess: refresh })
  const current = detail.data
  const versions = current?.versions ?? []
  const latest = versions.at(-1)
  const segments = [...new Set((original.data?.sources ?? current?.reviews.flatMap(r => r.result?.sources ?? []) ?? []).map(s => s.data.segment).filter((s): s is string => typeof s === 'string' && s !== 'consolidated'))]
  const start = (e: FormEvent) => { e.preventDefault(); extract.mutate() }
  return <>
    <PageHeader title={text('投资观点跟踪器', 'Investment hypothesis tracker')} description={text('把研究结论变成可重复检验的条件，追踪新财报对原判断的影响。', 'Turn research claims into repeatable tests and inspect what new evidence changes.')} />
    <p className="mb-5 text-xs leading-6 text-muted">{text('当前覆盖 SEC 财报驱动的数值假设，不覆盖全部新闻或盘中事件。定性观点可保存，但不会自动判断成立。观点状态、数据新鲜度和任务状态分别展示。', 'SEC financial-filing-driven quantitative hypotheses only. Qualitative beliefs can be saved without automatic truth judgments. Assessment, data freshness and job health are separate.')}</p>
    <div className="grid items-start gap-5 lg:grid-cols-[290px_minmax(0,1fr)]">
      <aside className="space-y-4"><Card><CardHeader title={text('从研究报告提取', 'Extract from research')} /><CardBody><form className="space-y-3" onSubmit={start}><select aria-label={text('原始研究报告', 'Original research report')} className={selectClass} value={sourceId} onChange={e => setSourceId(e.target.value)}><option value="">{text('选择已生成的报告', 'Choose a finished report')}</option>{reports.data?.filter(r => !busy(r.status)).map(r => <option key={r.id} value={r.id}>{r.ticker} · {r.as_of} · {r.question.slice(0, 30)}</option>)}</select><Button type="submit" loading={extract.isPending} disabled={!sourceId}>{text('提取候选观点', 'Extract candidates')}</Button>{extract.isError && <p role="alert" className="text-xs text-warn">{extract.error.message}</p>}</form></CardBody></Card>
        <Card><CardHeader title={text('观点记录', 'Hypotheses')} /><CardBody className="space-y-3">{history.data?.map(t => <Link key={t.id} to={`/theses/${t.id}`} className="block rounded border border-line p-3 text-xs leading-6"><strong>{t.ticker} · {label(t.lifecycle)}</strong><p>{t.statement}</p><p className="text-muted">{label(t.judgment)} · {label(t.data_health === 'partial' ? 'partial_data' : t.data_health)}</p></Link>)}{history.isError && <ErrorState error={history.error} />}</CardBody></Card>
      </aside>
      <main className="space-y-5">
        {extraction.data && !id && <><p role="status" className="text-sm">{text('候选提取：', 'Extraction: ')}{label(extraction.data.status)}</p>{extraction.data.error && <p role="alert" className="text-warn">{extraction.data.error}</p>}{extraction.data.candidates.map((c, i) => <CandidateCard key={`${extractionId}-${i}`} candidate={c} index={i} extractionId={extractionId!} segments={segments} />)}</>}
        {detail.isError && <ErrorState error={detail.error} />}
        {current && <><Card><CardHeader title={`${current.ticker} · ${label(current.lifecycle)}`} /><CardBody className="space-y-3"><p className="text-sm">{text('当前已确认版本：', 'Current confirmed version: ')}{current.current_version || text('无', 'None')} · {label(current.judgment)}</p><p className="text-xs text-muted">{text('数据：', 'Data: ')}{label(current.data_health === 'partial' ? 'partial_data' : current.data_health)} · {text('上次检查：', 'Last check: ')}{current.last_checked_at ?? '—'}</p>{latest && latest.number !== current.current_version && <p className="text-xs text-warn">{text('新版本未确认前，原已确认版本保持不变。', 'The confirmed version remains unchanged until the new version is confirmed.')}</p>}
          {current.current_version > 0 && <><div className="flex flex-wrap items-end gap-2"><Field label={text('复查披露截止日（留空为今天）', 'Review filing cutoff (blank for today)')}><Input type="date" min={latest?.origin.source_cutoff} max={toISODate(new Date())} value={asOf} onChange={e => setAsOf(e.target.value)} /></Field><Button loading={check.isPending} disabled={current.reviews.some(r => busy(r.status))} onClick={() => check.mutate()}>{text('按已确认规则复查', 'Review locked rule')}</Button></div><div className="flex gap-2"><Button onClick={() => lifecycle.mutate(current.lifecycle === 'active' ? 'paused' : 'active')}>{current.lifecycle === 'active' ? text('暂停自动追踪', 'Pause automatic tracking') : text('开启自动追踪', 'Enable automatic tracking')}</Button><Button onClick={() => lifecycle.mutate('archived')}>{text('归档', 'Archive')}</Button></div></>}{(check.error || lifecycle.error) && <p role="alert" className="text-xs text-warn">{(check.error || lifecycle.error)?.message}</p>}
        </CardBody></Card>
          {[...versions].reverse().map(v => {
            const panel = <VersionPanel version={v} latest={v.number === latest?.number} baseline={current.reviews.find(r => r.id === v.baseline_review_id)} segments={segments} thesisId={current.id} onRefresh={refresh} />
            return v.number === latest?.number || v.number === current.current_version ? <div key={v.id}>{panel}</div> : <details key={v.id}><summary className="cursor-pointer text-xs text-muted">{text('历史版本', 'Historical version')} v{v.number}</summary><div className="mt-3">{panel}</div></details>
          })}
          <Card><CardHeader title={text('复查时间线', 'Review timeline')} /><CardBody>{current.reviews.filter(r => r.kind !== 'baseline').map(r => <ReviewCard key={r.id} review={r} onRead={() => { void theses.read(current.id, r.id).then(refresh) }} />)}</CardBody></Card>
        </>}
        {!id && !extractionId && <Card><CardBody><p className="text-sm leading-7 text-muted">{text('先选择一份研究报告。AI 会提出候选观点，并区分直接检验、部分条件、代理指标和新假设。通过检查后，再由你确认实际运行的规则。', 'Choose a research report. Candidates distinguish direct tests, partial conditions, proxies and new hypotheses. You confirm the exact executable rule after verification.')}</p></CardBody></Card>}
      </main>
    </div>
  </>
}
