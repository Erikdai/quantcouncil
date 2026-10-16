"""Question-driven SEC research: create, inspect, cancel, retry and export."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select

from quantcouncil import llm_settings
from quantcouncil.api.deps import RateLimited, SessionDep
from quantcouncil.db.models import ResearchJob
from quantcouncil.deep_research.schemas import ResearchCreate, ResearchDetail, ResearchSummary
from quantcouncil.deep_research.service import ACTIVE
from quantcouncil.markets import resolve_instrument

router = APIRouter(prefix="/api/deep-research", tags=["deep research"])


async def load(session, job_id: str) -> ResearchJob:
    job = await session.get(ResearchJob, job_id)
    if job is None:
        raise HTTPException(404, "Research job not found")
    return job


@router.post("", response_model=ResearchDetail, status_code=201, dependencies=[RateLimited])
async def create(body: ResearchCreate, session: SessionDep):
    from quantcouncil.worker.tasks import deep_research  # noqa: PLC0415

    try:
        instrument = resolve_instrument(body.ticker)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if instrument.is_cn:
        raise HTTPException(422, "This research workspace supports US domestic SEC filers only")
    as_of = body.as_of or date.today()
    if as_of > date.today():
        raise HTTPException(422, "as_of cannot be in the future")
    settings, overrides = await llm_settings.resolve(session)
    if not overrides.get("api_key"):
        raise HTTPException(422, "Configure a model API key in Settings before starting research")
    job = ResearchJob(
        id=str(uuid.uuid4()),
        ticker=instrument.ticker,
        question=body.question,
        as_of=as_of,
        language=body.language,
        status="queued",
        stage="queued",
        sources=[],
        events=[],
        model=settings.model_dump(),
        manifest=[],
        warnings=[],
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    try:
        await deep_research.kiq(job.id)
    except Exception as exc:
        job.status, job.stage = "failed", "failed"
        job.error = f"The research worker could not be queued ({type(exc).__name__}). Check Redis/worker and retry."
        await session.commit()
    return ResearchDetail.model_validate(job)


@router.get("", response_model=list[ResearchSummary])
async def list_jobs(session: SessionDep, limit: int = Query(30, ge=1, le=100)):
    rows = (
        (
            await session.execute(
                select(ResearchJob).order_by(ResearchJob.created_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [ResearchSummary.model_validate(row) for row in rows]


@router.get("/{job_id}", response_model=ResearchDetail)
async def detail(job_id: str, session: SessionDep):
    return ResearchDetail.model_validate(await load(session, job_id))


@router.post("/{job_id}/cancel", response_model=ResearchDetail)
async def cancel(job_id: str, session: SessionDep):
    job = await session.get(ResearchJob, job_id, with_for_update=True)
    if job is None:
        raise HTTPException(404, "Research job not found")
    if job.status in ACTIVE:
        job.status, job.stage = "cancelled", "cancelled"
        job.updated_at = datetime.now(UTC)
        await session.commit()
    return ResearchDetail.model_validate(job)


@router.post(
    "/{job_id}/retry", response_model=ResearchDetail, status_code=201, dependencies=[RateLimited]
)
async def retry(job_id: str, session: SessionDep):
    job = await load(session, job_id)
    if job.status in ACTIVE:
        raise HTTPException(409, "Research is still active; cancel it before starting again")
    return await create(
        ResearchCreate(
            ticker=job.ticker, question=job.question, as_of=job.as_of, language=job.language
        ),
        session,
    )


@router.get("/{job_id}/report.md")
async def export_report(job_id: str, session: SessionDep):
    job = await load(session, job_id)
    if not job.report:
        raise HTTPException(409, "The report is not ready")
    report = job.report
    lines = [
        f"# {report['title']}",
        f"\n{job.ticker} | as of {job.as_of} | {job.status}",
        f"\nQuestion: {job.question}",
        f"\nVerdict: {report['verdict']}",
        "\nMonetary figures default to USD million unless explicitly labelled otherwise.",
    ]
    if job.verification:
        lines.append("\n## Verification")
        lines.append(f"\nChecks passed: {job.verification['passed']}")
        lines.extend(f"- {error}" for error in job.verification.get("errors", []))
        if job.verification.get("semantic_review"):
            lines.append(
                "\nA separate model reviewed units, periods and claim support. This is fallible, not an independent financial audit."
            )
    for title, findings in [
        ("Answer", [report["answer"]]),
        ("Findings", report["findings"]),
        ("Counterarguments", report["counterarguments"]),
    ]:
        lines.append(f"\n## {title}")
        for finding in findings:
            refs = " ".join(f"[{c['source_id']}]" for c in finding["citations"])
            lines.append(f"\n- ({finding['kind']}) {finding['text']} {refs}")
    for title, key in [
        ("Unknowns", "unknowns"),
        ("What would change the answer", "what_would_change"),
    ]:
        lines.append(f"\n## {title}")
        lines.extend(f"- {line}" for line in report[key])
    lines.append("\n## Evidence snapshots")
    used = {
        c["source_id"]
        for finding in [report["answer"], *report["findings"], *report["counterarguments"]]
        for c in finding["citations"]
    }
    by_id = {source["id"]: source for source in job.sources}
    pending = list(used)
    while pending:
        for input_id in by_id.get(pending.pop(), {}).get("inputs", []):
            if input_id not in used:
                used.add(input_id)
                pending.append(input_id)
    for source in job.sources:
        if source["id"] not in used:
            continue
        lines.append(
            f"\n### [{source['id']}] {source['title']}\n{source['url']}\nFiled: {source['filed']}\n\n{source['content']}\n\nSHA-256: {source.get('sha256') or 'derived; see input sources'}"
        )
    lines.append(
        "\nSource IDs, exact quotes and numeric occurrence are checked, not the meaning of every number or the correctness of every inference. Research only."
    )
    return Response(
        "\n".join(lines),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{job.ticker}-research-{job.id[:8]}.md"'
        },
    )
