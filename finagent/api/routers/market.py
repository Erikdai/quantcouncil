"""Market data for charts, and the watchlist that the scheduled scan analyzes."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select

from finagent.api.deps import SessionDep
from finagent.api.schemas import Bar, KlineOut, WatchItem
from finagent.db.models import WatchItem as WatchRow
from finagent.markets import display_name, resolve_instrument

router = APIRouter(tags=["market"])


def _bars(ticker: str, market: str, start: date, end: date) -> list[Bar]:
    if market == "CN":
        from tradingagents.dataflows.vendors.cn.market import load_cn_ohlcv  # noqa: PLC0415

        df = load_cn_ohlcv(ticker, end.isoformat(), fill_gaps=False)
    else:
        from tradingagents.dataflows.config import run_config  # noqa: PLC0415
        from tradingagents.dataflows.vendors.yahoo.ohlcv import load_ohlcv  # noqa: PLC0415

        with run_config({}):
            df = load_ohlcv(ticker, end.isoformat(), fill_gaps=False)
    df = df[df["Date"] >= str(start)].dropna(subset=["Close"])
    return [Bar(time=d.strftime("%Y-%m-%d"), open=float(o), high=float(h), low=float(lo), close=float(c),
                volume=float(v or 0))
            for d, o, h, lo, c, v in zip(df["Date"], df["Open"], df["High"], df["Low"], df["Close"], df["Volume"],
                                         strict=True)]


@router.get("/api/market/kline/{ticker}", response_model=KlineOut)
async def kline(ticker: str, start: date | None = None, end: date | None = None) -> KlineOut:
    try:
        instrument = resolve_instrument(ticker)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    end = end or date.today()
    start = start or end - timedelta(days=240)
    try:
        bars = await asyncio.to_thread(_bars, instrument.ticker, instrument.market, start, end)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"market data unavailable: {exc}") from exc
    name = await asyncio.to_thread(display_name, instrument)
    return KlineOut(ticker=instrument.ticker, name=name, bars=bars)


class WatchBody(BaseModel):
    ticker: str


@router.get("/api/watchlist", response_model=list[WatchItem])
async def watchlist(session: SessionDep) -> list[WatchItem]:
    rows = (await session.execute(select(WatchRow).order_by(WatchRow.added_at))).scalars().all()
    return [WatchItem(ticker=r.ticker, name=r.name, enabled=r.enabled, added_at=r.added_at) for r in rows]


@router.post("/api/watchlist", response_model=WatchItem, status_code=201)
async def add_watch(body: WatchBody, session: SessionDep) -> WatchItem:
    try:
        instrument = resolve_instrument(body.ticker)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    row = await session.get(WatchRow, instrument.ticker)
    if row is None:
        row = WatchRow(ticker=instrument.ticker, enabled=True,
                       name=await asyncio.to_thread(display_name, instrument))
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return WatchItem(ticker=row.ticker, name=row.name, enabled=row.enabled, added_at=row.added_at)


@router.delete("/api/watchlist/{ticker}", status_code=204)
async def remove_watch(ticker: str, session: SessionDep) -> Response:
    row = await session.get(WatchRow, resolve_instrument(ticker).ticker)
    if row is not None:
        await session.delete(row)
        await session.commit()
    return Response(status_code=204)
