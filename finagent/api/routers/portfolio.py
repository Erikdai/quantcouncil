"""Paper account: positions marked to market, orders, ledger verification."""

from __future__ import annotations

import asyncio
from datetime import date

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finagent.api.deps import SessionDep
from finagent.api.schemas import AccountOut, OrderOut, PortfolioOut, PositionOut
from finagent.config import get_settings
from finagent.db.models import Order, Position
from finagent.portfolio import ledger

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _last_close(ticker: str) -> float | None:
    try:
        from tradingagents.dataflows.vendors.cn.market import latest_bar  # noqa: PLC0415

        return latest_bar(ticker, date.today().isoformat())["close"]
    except Exception:  # noqa: BLE001 — fall back to the last fill price
        return None


async def portfolio_out(session: AsyncSession, account_id: str) -> PortfolioOut:
    settings = get_settings()
    account = await ledger.ensure_account(session, account_id, settings.initial_cash)
    positions = (await session.execute(select(Position).where(Position.account_id == account_id,
                                                              Position.quantity > 0))).scalars().all()
    closes = await asyncio.gather(*(asyncio.to_thread(_last_close, p.ticker) for p in positions))
    today = date.today()
    rows, market_value = [], 0.0
    for p, close in zip(positions, closes, strict=True):
        price = close or float(p.last_price or p.avg_cost)
        value = price * p.quantity
        market_value += value
        rows.append(PositionOut(ticker=p.ticker, name=p.name, quantity=p.quantity, available_quantity=p.available(today),
                                avg_cost=float(p.avg_cost), last_price=price, market_value=round(value, 2),
                                unrealized_pnl=round((price - float(p.avg_cost)) * p.quantity, 2)))
    cash = float(account.cash)
    equity = cash + market_value
    peak = max(float(account.peak_equity), equity)
    for row in rows:
        row.weight = round((row.market_value or 0) / equity, 4) if equity else None
    initial = float(account.initial_cash)
    out = AccountOut(id=account_id, cash=round(cash, 2), initial_cash=initial, market_value=round(market_value, 2),
                     equity=round(equity, 2), pnl=round(equity - initial, 2),
                     pnl_pct=round((equity / initial - 1) if initial else 0, 4), peak_equity=round(peak, 2),
                     drawdown_pct=round(1 - equity / peak, 4) if peak else 0.0)
    await session.commit()
    return PortfolioOut(account=out, positions=rows, ledger_verified=await ledger.verify_chain(session, account_id))


@router.get("", response_model=PortfolioOut)
async def get_portfolio(session: SessionDep, account_id: str = "default") -> PortfolioOut:
    return await portfolio_out(session, account_id)


@router.get("/orders", response_model=list[OrderOut])
async def list_orders(session: SessionDep, account_id: str = "default",
                      limit: int = Query(50, le=500)) -> list[OrderOut]:
    rows = (await session.execute(select(Order).where(Order.account_id == account_id)
                                  .order_by(Order.created_at.desc()).limit(limit))).scalars().all()
    return [OrderOut(id=o.id, run_id=o.run_id, ticker=o.ticker, side=o.side, quantity=o.quantity,
                     price=float(o.price), fees=float(o.fees), status=o.status, comment=o.comment,
                     created_at=o.created_at) for o in rows]


class ResetBody(BaseModel):
    initial_cash: float = 1_000_000.0


@router.post("/reset", response_model=PortfolioOut)
async def reset(body: ResetBody, session: SessionDep, account_id: str = "default") -> PortfolioOut:
    await ledger.reset_account(session, account_id, body.initial_cash)
    await session.commit()
    return await portfolio_out(session, account_id)
