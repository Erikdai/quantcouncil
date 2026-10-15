"""One-click exports: the daily report and a run's research report, as PDF or Word."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from quantcouncil.api.deps import SessionDep
from quantcouncil.db.models import Order, Run
from quantcouncil.markets import CN, latest_trading_day
from quantcouncil.portfolio.snapshot import portfolio_snapshot
from quantcouncil.reports import MEDIA_TYPES, daily_report, render, run_report

router = APIRouter(tags=["reports"])

Format = Literal["pdf", "docx"]
Lang = Literal["zh", "en"]


def _file(content: bytes, fmt: str, filename: str) -> Response:
    disposition = f"attachment; filename=report.{fmt}; filename*=UTF-8''{quote(filename)}"
    return Response(content, media_type=MEDIA_TYPES[fmt], headers={"Content-Disposition": disposition})


@router.get("/api/reports/daily")
async def export_daily(session: SessionDep, day: date | None = None, format: Format = "pdf",  # noqa: A002
                       lang: Lang = "zh", account_id: str = "default") -> Response:
    """Account, positions, the day's analyses with their decisions and risk checks, and fills."""
    day = day or await asyncio.to_thread(latest_trading_day, CN)
    portfolio = await portfolio_snapshot(session, account_id)
    runs = (await session.execute(select(Run).where(Run.trade_date == day).order_by(Run.created_at))).scalars().all()
    orders = (await session.execute(select(Order).where(Order.account_id == account_id, Order.trade_date == day)
                                    .order_by(Order.created_at))).scalars().all()
    report = daily_report(day, portfolio, list(runs), list(orders), lang)
    content = await asyncio.to_thread(render, report, format)
    return _file(content, format, f"QuantCouncil_daily_{day.isoformat()}.{format}")


@router.get("/api/runs/{run_id}/report")
async def export_run(run_id: str, session: SessionDep, format: Format = "pdf",  # noqa: A002
                     lang: Lang = "zh") -> Response:
    """The full research report of one run: decision, risk check, plans, analyst reports, debates."""
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    content = await asyncio.to_thread(render, run_report(run, lang), format)
    return _file(content, format, f"QuantCouncil_{run.ticker}_{run.trade_date}.{format}")
