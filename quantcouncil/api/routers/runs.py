"""Runs: start an analysis, follow it live (SSE), approve its order, evaluate it."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from quantcouncil.api.deps import BusDep, RateLimited, SessionDep
from quantcouncil.api.schemas import (
    TERMINAL_STATUSES,
    ApprovalRequest,
    EvalResultOut,
    RunCreate,
    RunEventType,
    RunOut,
    RunStatus,
    RunSummary,
)
from quantcouncil.db import get_sessionmaker
from quantcouncil.db.models import Run
from quantcouncil.markets import core_analysts, display_name, latest_trading_day, resolve_instrument

router = APIRouter(prefix="/api/runs", tags=["runs"])


def run_out(run: Run) -> RunOut:
    from quantcouncil.observability.tracing import trace_url  # noqa: PLC0415

    evals = [EvalResultOut(id=e.id, run_id=e.run_id, evaluator=e.evaluator, scores=e.scores, passed=e.passed,
                           comment=e.comment, created_at=e.created_at) for e in (run.evals or [])]
    return RunOut(
        id=run.id, ticker=run.ticker, name=run.name, market=run.market, trade_date=run.trade_date,
        status=RunStatus(run.status), rating=run.rating, created_at=run.created_at, finished_at=run.finished_at,
        analysts=list(run.analysts or []), auto_approve=run.auto_approve, reports=run.reports or {},
        investment_debate=run.investment_debate, risk_debate=run.risk_debate, investment_plan=run.investment_plan,
        trader_plan=run.trader_plan, final_decision=run.final_decision, risk_check=run.risk_check,
        approval=run.approval, execution=run.execution, error=run.error,
        trace_url=(run.options or {}).get("trace_url") or trace_url(run.trace_id),
        llm=(run.options or {}).get("llm"), evals=evals)


async def _load(session: AsyncSession, run_id: str) -> Run:
    run = (await session.execute(select(Run).options(selectinload(Run.evals)).where(Run.id == run_id))
           ).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")
    return run


@router.post("", response_model=RunOut, status_code=201, dependencies=[RateLimited])
async def create_run(body: RunCreate, session: SessionDep,
                     bus: BusDep) -> RunOut:
    from quantcouncil.worker.tasks import run_analysis  # noqa: PLC0415

    try:
        instrument = resolve_instrument(body.ticker)
        analysts = body.analysts or ["market", "sentiment", "news", "fundamentals"]
        core_analysts(instrument.market, analysts)  # validates names
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    trade_date = body.trade_date or await asyncio.to_thread(latest_trading_day, instrument.market)
    if trade_date > date.today():
        raise HTTPException(422, "trade_date cannot be in the future")
    name = await asyncio.to_thread(display_name, instrument)
    run = Run(id=str(uuid.uuid4()), ticker=instrument.ticker, name=name, market=instrument.market,
              trade_date=trade_date, status=RunStatus.queued.value, analysts=analysts,
              auto_approve=body.auto_approve, account_id=body.account_id, source="api",
              options={"max_debate_rounds": body.max_debate_rounds} if body.max_debate_rounds else {},
              reports={})
    session.add(run)
    await session.commit()
    await bus.publish(run.id, RunEventType.status, {"status": RunStatus.queued.value})
    await run_analysis.kiq(run.id)
    return run_out(await _load(session, run.id))


@router.get("", response_model=list[RunSummary])
async def list_runs(session: SessionDep, limit: int = Query(50, le=200), status: RunStatus | None = None,
                    ticker: str | None = None) -> list[RunSummary]:
    q = select(Run).order_by(Run.created_at.desc()).limit(limit)
    if status:
        q = q.where(Run.status == status.value)
    if ticker:
        q = q.where(Run.ticker == resolve_instrument(ticker).ticker)
    rows = (await session.execute(q)).scalars().all()
    return [RunSummary(id=r.id, ticker=r.ticker, name=r.name, market=r.market, trade_date=r.trade_date,
                       status=RunStatus(r.status), rating=r.rating, created_at=r.created_at,
                       finished_at=r.finished_at) for r in rows]


@router.get("/{run_id}", response_model=RunOut)
async def get_run(run_id: str, session: SessionDep) -> RunOut:
    return run_out(await _load(session, run_id))


@router.get("/{run_id}/events")
async def run_events(run_id: str, request: Request, session: SessionDep,
                     bus: BusDep):
    """Server-Sent Events: the run's history from ``Last-Event-ID`` (or the start), then live."""
    run = await _load(session, run_id)
    start = request.headers.get("last-event-id") or request.query_params.get("from") or "0"
    terminal_at_open = RunStatus(run.status) in TERMINAL_STATUSES

    async def stream():
        last = start
        idle = 0
        while True:
            if await request.is_disconnected():
                return
            batch = await bus.read(run_id, last, block_ms=10_000)
            if not batch:
                idle += 1
                if terminal_at_open or idle >= 3:
                    # The stream may have expired or never existed (old runs): settle from the DB.
                    async with get_sessionmaker()() as fresh:  # the request's session is stale here
                        current = await fresh.get(Run, run_id)
                    if current is None or RunStatus(current.status) in TERMINAL_STATUSES:
                        yield {"event": "done", "data": json.dumps({
                            "type": "done", "run_id": run_id, "ts": None,
                            "data": {"status": current.status if current else "missing"}})}
                        return
                    idle = 0
                continue
            idle = 0
            for event_id, event in batch:
                last = event_id
                yield {"id": event_id, "event": event["type"], "data": json.dumps(event, ensure_ascii=False)}
                if event["type"] == RunEventType.done:
                    return

    return EventSourceResponse(stream(), ping=15, headers={"X-Accel-Buffering": "no"})


@router.post("/{run_id}/approval", response_model=RunOut)
async def approve(run_id: str, body: ApprovalRequest, session: SessionDep) -> RunOut:
    from quantcouncil.worker.tasks import resume_analysis  # noqa: PLC0415

    run = await _load(session, run_id)
    if run.status != RunStatus.awaiting_approval.value:
        raise HTTPException(409, f"run is {run.status}, not awaiting approval")
    if body.action == "modify" and (body.quantity is None or body.quantity <= 0):
        raise HTTPException(422, "modify needs a positive quantity")
    await resume_analysis.kiq(run_id, body.model_dump())
    return run_out(run)


@router.post("/{run_id}/retry", response_model=RunOut)
async def retry(run_id: str, session: SessionDep) -> RunOut:
    """Resume a failed run from its last checkpoint (completed agents are not re-run)."""
    from quantcouncil.worker.tasks import retry_analysis  # noqa: PLC0415

    run = await _load(session, run_id)
    if run.status != RunStatus.failed.value:
        raise HTTPException(409, f"run is {run.status}; only failed runs can be retried")
    await retry_analysis.kiq(run_id)
    return run_out(run)


@router.post("/{run_id}/evaluate", response_model=EvalResultOut)
async def evaluate_run(run_id: str, session: SessionDep) -> EvalResultOut:
    from quantcouncil.evals.judge import evaluate_and_store  # noqa: PLC0415

    run = await _load(session, run_id)
    if not run.final_decision:
        raise HTTPException(409, "the run has no decision to evaluate yet")
    return await evaluate_and_store(run_id)
