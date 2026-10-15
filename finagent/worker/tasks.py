"""Background tasks: analyses, approvals, ingestion, and the after-close schedule."""

from __future__ import annotations

import logging
import uuid
from datetime import date

from sqlalchemy import select

from finagent.config import get_settings
from finagent.db import session_scope
from finagent.db.models import Run, WatchItem
from finagent.markets import latest_trading_day, resolve_instrument
from finagent.worker.broker import broker

logger = logging.getLogger(__name__)
_settings = get_settings()
_CN_TZ = "Asia/Shanghai"


@broker.task(task_name="finagent.run_analysis")
async def run_analysis(run_id: str) -> str:
    from finagent.graph.runner import start_run  # noqa: PLC0415

    return await start_run(run_id)


@broker.task(task_name="finagent.resume_analysis")
async def resume_analysis(run_id: str, decision: dict) -> str:
    from finagent.graph.runner import resume_run  # noqa: PLC0415

    return await resume_run(run_id, decision)


@broker.task(task_name="finagent.retry_analysis")
async def retry_analysis(run_id: str) -> str:
    from finagent.graph.runner import retry_run  # noqa: PLC0415

    return await retry_run(run_id)


@broker.task(task_name="finagent.ingest_documents")
async def ingest_documents(ticker: str, kinds: list[str], since: str | None = None, limit: int = 10) -> dict:
    from finagent.rag.ingest import ingest_ticker  # noqa: PLC0415

    return await ingest_ticker(ticker, kinds, since=date.fromisoformat(since) if since else None, limit=limit)


@broker.task(task_name="finagent.evaluate_run")
async def evaluate_run(run_id: str) -> dict:
    from finagent.evals.judge import evaluate_and_store  # noqa: PLC0415

    return (await evaluate_and_store(run_id)).model_dump(mode="json")


@broker.task(task_name="finagent.scan_watchlist",
             schedule=[{"cron": _settings.watchlist_scan_cron, "cron_offset": _CN_TZ}])
async def scan_watchlist() -> list[str]:
    """After the close: analyze every enabled watchlist name, auto-approving within risk limits."""
    async with session_scope() as session:
        items = (await session.execute(select(WatchItem).where(WatchItem.enabled.is_(True)))).scalars().all()
        trade_date = latest_trading_day("CN")
        run_ids = []
        for item in items:
            instrument = resolve_instrument(item.ticker)
            run = Run(id=str(uuid.uuid4()), ticker=instrument.ticker, name=item.name, market=instrument.market,
                      trade_date=trade_date, status="queued", analysts=["market", "sentiment", "news", "fundamentals"],
                      auto_approve=True, account_id=_settings.default_account, source="schedule", options={},
                      reports={})
            session.add(run)
            run_ids.append(run.id)
    for run_id in run_ids:
        await run_analysis.kiq(run_id)
    logger.info("watchlist scan queued %d runs for %s", len(run_ids), trade_date)
    return run_ids


@broker.task(task_name="finagent.reap_stale_runs", schedule=[{"cron": "*/10 * * * *"}])
async def reap_stale_runs(max_minutes: int = 45) -> list[str]:
    """Fail runs whose worker died mid-run (status stuck at running), so they can be
    retried from their last checkpoint instead of hanging forever."""
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    from finagent.api.schemas import RunEventType, RunStatus  # noqa: PLC0415
    from finagent.runtime import get_runtime  # noqa: PLC0415

    cutoff = datetime.now(UTC) - timedelta(minutes=max_minutes)
    async with session_scope() as session:
        stale = (await session.execute(select(Run).where(Run.status == RunStatus.running.value,
                                                         Run.started_at < cutoff))).scalars().all()
        for run in stale:
            run.status = RunStatus.failed.value
            run.error = f"worker lost: no progress for {max_minutes} min; retry resumes from the last checkpoint"
            run.finished_at = datetime.now(UTC)
        ids = [r.id for r in stale]
    bus = get_runtime().bus
    for run_id in ids:
        if bus is not None:
            await bus.publish(run_id, RunEventType.error, {"message": "worker lost; retry to resume"})
            await bus.publish(run_id, RunEventType.done, {"status": RunStatus.failed.value})
    if ids:
        logger.warning("reaped %d stale runs: %s", len(ids), ids)
    return ids


@broker.task(task_name="finagent.settle_memory", schedule=[{"cron": _settings.settle_cron, "cron_offset": _CN_TZ}])
async def settle_memory() -> dict:
    """Settle due decisions (realized alpha + reflection) and index the lessons for semantic recall."""
    import asyncio  # noqa: PLC0415

    from finagent.graph.core import get_core  # noqa: PLC0415
    from finagent.markets import CN_DEFAULT  # noqa: PLC0415
    from finagent.memory.store import sync_lessons  # noqa: PLC0415
    from finagent.runtime import get_runtime  # noqa: PLC0415

    core = get_core(CN_DEFAULT, None, store=get_runtime().store)  # env-default models
    settlement = await asyncio.to_thread(core.settle_all_pending)
    indexed = await sync_lessons(get_runtime().store, core.memory_log)
    return {"settled": len(settlement.settled), "failed": len(settlement.failed), "lessons_indexed": indexed}
