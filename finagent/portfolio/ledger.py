"""Paper-trading book: T+1 position locks, A-share fees and a hash-chained ledger."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from finagent.api.schemas import Execution, OrderProposal
from finagent.config import FeeSchedule, get_fee_schedule
from finagent.db.models import Account, LedgerEntry, Order, Position
from finagent.risk.engine import BookView, Holding, estimate_fees

GENESIS = "0" * 64
CENT = Decimal("0.01")


def _d(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def chain_hash(prev_hash: str, payload: dict) -> str:
    return hashlib.sha256((prev_hash + _canonical(payload)).encode()).hexdigest()


async def _append(session: AsyncSession, account_id: str, kind: str, payload: dict) -> LedgerEntry:
    last = (await session.execute(
        select(LedgerEntry).where(LedgerEntry.account_id == account_id).order_by(LedgerEntry.seq.desc()).limit(1)
    )).scalar_one_or_none()
    seq = (last.seq + 1) if last else 1
    prev = last.hash if last else GENESIS
    entry = LedgerEntry(account_id=account_id, seq=seq, kind=kind, payload=payload, prev_hash=prev,
                        hash=chain_hash(prev, {"seq": seq, "kind": kind, **payload}))
    session.add(entry)
    return entry


async def verify_chain(session: AsyncSession, account_id: str) -> bool:
    entries = (await session.execute(
        select(LedgerEntry).where(LedgerEntry.account_id == account_id).order_by(LedgerEntry.seq)
    )).scalars().all()
    prev = GENESIS
    for i, e in enumerate(entries, start=1):
        if e.seq != i or e.prev_hash != prev or e.hash != chain_hash(prev, {"seq": e.seq, "kind": e.kind, **e.payload}):
            return False
        prev = e.hash
    return True


async def ensure_account(session: AsyncSession, account_id: str, initial_cash: float) -> Account:
    account = await session.get(Account, account_id, with_for_update=True)
    if account is None:
        cash = _d(initial_cash)
        account = Account(id=account_id, cash=cash, initial_cash=cash, peak_equity=cash)
        session.add(account)
        await session.flush()
        await _append(session, account_id, "open", {"cash": str(cash)})
    return account


async def reset_account(session: AsyncSession, account_id: str, initial_cash: float) -> Account:
    """Liquidate to cash at ``initial_cash`` (demo helper); the reset is itself journaled."""
    account = await ensure_account(session, account_id, initial_cash)
    positions = (await session.execute(select(Position).where(Position.account_id == account_id))).scalars().all()
    for p in positions:
        await session.delete(p)
    cash = _d(initial_cash)
    account.cash, account.initial_cash, account.peak_equity = cash, cash, cash
    await _append(session, account_id, "reset", {"cash": str(cash)})
    return account


async def orders_on(session: AsyncSession, account_id: str, trade_date: date) -> int:
    return (await session.execute(select(func.count()).select_from(Order).where(
        Order.account_id == account_id, Order.trade_date == trade_date, Order.status == "filled"))).scalar_one()


async def book_view(session: AsyncSession, account_id: str, trade_date: date, initial_cash: float,
                    price_of: Callable[[str], float | None] | None = None) -> BookView:
    """The account as the risk engine sees it on ``trade_date`` (T+1 locks applied)."""
    account = await ensure_account(session, account_id, initial_cash)
    positions = (await session.execute(select(Position).where(Position.account_id == account_id))).scalars().all()
    holdings = {}
    for p in positions:
        if p.quantity <= 0:
            continue
        price = (price_of(p.ticker) if price_of else None) or float(p.last_price or p.avg_cost)
        holdings[p.ticker] = Holding(quantity=p.quantity, available=p.available(trade_date),
                                     avg_cost=float(p.avg_cost), last_price=float(price))
    view = BookView(cash=float(account.cash), peak_equity=float(account.peak_equity), positions=holdings,
                    orders_today=await orders_on(session, account_id, trade_date))
    if view.equity > view.peak_equity:
        account.peak_equity = _d(view.equity)
        view.peak_equity = view.equity
    return view


async def execute(session: AsyncSession, account_id: str, order: OrderProposal, trade_date: date,
                  run_id: str | None, initial_cash: float, comment: str | None = None,
                  name: str | None = None, fees: FeeSchedule | None = None) -> Execution:
    """Fill a vetted order at its reference price. Idempotent per run: a retried
    execution returns the fill already booked instead of trading twice."""
    fees = fees or get_fee_schedule()
    if run_id:
        done = (await session.execute(select(Order).where(Order.run_id == run_id, Order.status == "filled"))
                ).scalar_one_or_none()
        if done is not None:
            account = await session.get(Account, account_id)
            return Execution(order_id=done.id, ticker=done.ticker, side=done.side, quantity=done.quantity,
                             price=float(done.price), fees={k: float(v) for k, v in done.fee_detail.items()},
                             cash_after=float(account.cash), status="filled", reason="already executed")

    account = await ensure_account(session, account_id, initial_cash)  # row lock serializes fills
    position = await session.get(Position, (account_id, order.ticker), with_for_update=True)
    price = _d(order.price)
    qty = int(order.quantity)
    fee_detail = estimate_fees(order.side, qty, float(price), fees)
    total_fees = _d(fee_detail["total"])
    notional = (price * qty).quantize(CENT)
    order_id = str(uuid.uuid4())

    def reject(reason: str) -> Execution:
        session.add(Order(id=order_id, account_id=account_id, run_id=run_id, ticker=order.ticker, side=order.side,
                          quantity=qty, price=price, fees=Decimal(0), fee_detail={}, trade_date=trade_date,
                          status="rejected", comment=reason))
        return Execution(order_id=order_id, ticker=order.ticker, side=order.side, quantity=qty, price=float(price),
                         fees={}, cash_after=float(account.cash), status="rejected", reason=reason)

    if qty <= 0:
        return reject("zero quantity")
    if order.side == "buy":
        cost = notional + total_fees
        if cost > account.cash:
            return reject(f"cash {account.cash} < cost {cost}")
        account.cash -= cost
        if position is None:
            position = Position(account_id=account_id, ticker=order.ticker, name=name, quantity=0,
                                avg_cost=Decimal(0), locked_quantity=0)
            session.add(position)
        held_cost = position.avg_cost * position.quantity
        position.quantity += qty
        position.avg_cost = _d((held_cost + cost) / position.quantity)  # fees are part of cost basis
        # T+1: today's buys are locked until the next session.
        if position.locked_date == trade_date:
            position.locked_quantity += qty
        else:
            position.locked_quantity, position.locked_date = qty, trade_date
    else:
        if position is None or position.available(trade_date) < qty:
            return reject("not enough sellable shares (T+1)")
        account.cash += notional - total_fees
        position.quantity -= qty
        if position.quantity == 0:
            position.avg_cost = Decimal(0)
    position.last_price = price
    if name and not position.name:
        position.name = name

    session.add(Order(id=order_id, account_id=account_id, run_id=run_id, ticker=order.ticker, side=order.side,
                      quantity=qty, price=price, fees=total_fees, fee_detail=fee_detail, trade_date=trade_date,
                      status="filled", comment=comment))
    await _append(session, account_id, "fill", {
        "order_id": order_id, "run_id": run_id, "ticker": order.ticker, "side": order.side, "quantity": qty,
        "price": str(price), "fees": str(total_fees), "cash_after": str(account.cash),
        "position_after": position.quantity, "trade_date": trade_date.isoformat()})
    return Execution(order_id=order_id, ticker=order.ticker, side=order.side, quantity=qty, price=float(price),
                     fees=fee_detail, cash_after=float(account.cash), status="filled")
