"""Paper account: positions marked to market, orders, ledger verification."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from quantcouncil.api.deps import SessionDep
from quantcouncil.api.schemas import OrderOut, PortfolioOut
from quantcouncil.config import get_settings
from quantcouncil.db.models import Order, Position
from quantcouncil.markets import display_name, resolve_instrument
from quantcouncil.portfolio import ledger
from quantcouncil.portfolio.snapshot import portfolio_snapshot

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("", response_model=PortfolioOut)
async def get_portfolio(session: SessionDep, account_id: str = "default") -> PortfolioOut:
    return await portfolio_snapshot(session, account_id)


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
    return await portfolio_snapshot(session, account_id)


class HoldingBody(BaseModel):
    quantity: int = Field(ge=0, description="Shares held; 0 removes the holding")
    avg_cost: float = Field(gt=0, description="Average cost per share (CNY)")


class CashBody(BaseModel):
    cash: float = Field(ge=0)


@router.put("/positions/{ticker}", response_model=PortfolioOut)
async def set_holding(ticker: str, body: HoldingBody, session: SessionDep,
                      account_id: str = "default") -> PortfolioOut:
    """Enter or edit a holding you already own, so the agents decide with your real book."""
    try:
        instrument = resolve_instrument(ticker)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not instrument.is_cn:
        raise HTTPException(422, "the paper account holds A-shares only")
    name = await asyncio.to_thread(display_name, instrument)
    await ledger.set_holding(session, account_id, instrument.ticker, body.quantity, body.avg_cost,
                             get_settings().initial_cash, name=name)
    await session.commit()
    return await portfolio_snapshot(session, account_id)


@router.delete("/positions/{ticker}", response_model=PortfolioOut)
async def remove_holding(ticker: str, session: SessionDep, account_id: str = "default") -> PortfolioOut:
    instrument = resolve_instrument(ticker)
    position = await session.get(Position, (account_id, instrument.ticker))
    if position is None:
        raise HTTPException(404, "no such holding")
    await ledger.set_holding(session, account_id, instrument.ticker, 0, float(position.avg_cost),
                             get_settings().initial_cash)
    await session.commit()
    return await portfolio_snapshot(session, account_id)


@router.put("/cash", response_model=PortfolioOut)
async def set_cash(body: CashBody, session: SessionDep, account_id: str = "default") -> PortfolioOut:
    await ledger.set_cash(session, account_id, body.cash, get_settings().initial_cash)
    await session.commit()
    return await portfolio_snapshot(session, account_id)
