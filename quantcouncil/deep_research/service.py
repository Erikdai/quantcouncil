"""Durable job lifecycle; checkpoints make progress and partial evidence inspectable."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from quantcouncil import llm_settings
from quantcouncil.db import session_scope
from quantcouncil.db.models import ResearchJob
from quantcouncil.deep_research.engine import research

logger = logging.getLogger(__name__)
ACTIVE = ("queued", "running")


class ResearchStopped(Exception):
    pass


async def execute_job(job_id: str) -> str:
    async with session_scope() as session:
        job = await session.get(ResearchJob, job_id, with_for_update=True)
        if job is None or job.status != "queued":
            return job.status if job else "missing"
        job.status = "running"
        job.stage = "collecting"
        _, overrides = await llm_settings.resolve(session, job.model)
        ticker, question, as_of, language = job.ticker, job.question, job.as_of, job.language

    async def checkpoint(**changes):
        async with session_scope() as session:
            row = await session.get(ResearchJob, job_id, with_for_update=True)
            if row.status != "running":
                raise ResearchStopped()
            for key, value in changes.items():
                setattr(row, key, value)
            row.updated_at = datetime.now(UTC)

    async def progress(stage: str, message: str):
        async with session_scope() as session:
            row = await session.get(ResearchJob, job_id, with_for_update=True)
            if row.status != "running":
                raise ResearchStopped()
            row.stage = stage
            row.updated_at = datetime.now(UTC)
            row.events = [
                *(row.events or []),
                {"at": row.updated_at.isoformat(), "stage": stage, "message": message},
            ]

    try:
        async with asyncio.timeout(900):
            result = await research(
                ticker, question, as_of, language, overrides, progress, checkpoint
            )
        await checkpoint(status=result["status"], stage=result["status"])
        return result["status"]
    except ResearchStopped:
        return "stopped"
    except Exception as exc:
        logger.exception("research job %s failed", job_id)
        message = (
            "Research exceeded the 15-minute limit; retry the job."
            if isinstance(exc, TimeoutError)
            else f"{type(exc).__name__}: {str(exc)[:400]}"
        )
        async with session_scope() as session:
            row = await session.get(ResearchJob, job_id, with_for_update=True)
            if row and row.status == "running":
                row.status, row.stage, row.error = "failed", "failed", message
                row.updated_at = datetime.now(UTC)
        return "failed"


async def reap_jobs() -> list[str]:
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(ResearchJob)
                    .where(
                        ResearchJob.status.in_(ACTIVE),
                        ResearchJob.updated_at < datetime.now(UTC) - timedelta(minutes=30),
                    )
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.status, row.stage = "failed", "failed"
            row.error = "No progress for 30 minutes; the worker may have stopped. Retry to start a new research job."
        return [row.id for row in rows]
