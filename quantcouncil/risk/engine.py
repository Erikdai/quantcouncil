"""Deterministic pre-trade risk gate: sizes the order a rating implies and vets it.

A-share rules: 100-share lots, T+1, limit-up/down, suspension, ST stocks.
Book limits: weight per name, gross exposure, cash reserve, drawdown breaker,
orders per day. A human-resized order is re-checked by the same rules.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from quantcouncil.api.schemas import OrderProposal, RiskCheck, RiskViolation
from quantcouncil.config import FeeSchedule, RiskLimits

TRADEABLE = ("Buy", "Overweight", "Hold", "Underweight", "Sell")


@dataclass(frozen=True)
class MarketRef:
    """Unadjusted prices for the trade date (limits apply to traded prices)."""

    ticker: str
    trade_date: str
    bar_date: str
    close: float
    prev_close: float
    limit_up: float
    limit_down: float
    is_st: bool = False
    board: str = "main"
    name: str | None = None

    @property
    def suspended(self) -> bool:
        return self.bar_date != self.trade_date


@dataclass(frozen=True)
class Holding:
    quantity: int
    available: int
    avg_cost: float
    last_price: float


@dataclass
class BookView:
    cash: float
    peak_equity: float
    positions: dict[str, Holding] = field(default_factory=dict)
    orders_today: int = 0

    @property
    def market_value(self) -> float:
        return sum(h.quantity * h.last_price for h in self.positions.values())

    @property
    def equity(self) -> float:
        return self.cash + self.market_value

    @property
    def drawdown(self) -> float:
        return 0.0 if self.peak_equity <= 0 else max(0.0, 1 - self.equity / self.peak_equity)


def estimate_fees(side: str, quantity: int, price: float, fees: FeeSchedule) -> dict[str, float]:
    notional = quantity * price
    commission = max(fees.commission_min, notional * fees.commission_rate) if quantity else 0.0
    stamp = notional * fees.stamp_duty_rate if side == "sell" else 0.0
    transfer = notional * fees.transfer_fee_rate
    out = {"commission": round(commission, 2), "stamp_duty": round(stamp, 2), "transfer_fee": round(transfer, 2)}
    out["total"] = round(sum(out.values()), 2)
    return out


def fill_price(side: str, reference: float, fees: FeeSchedule) -> float:
    """Paper fill: the reference price moved against us by the slippage, to the fen."""
    slip = fees.slippage_bps / 10_000
    return round(reference * (1 + slip if side == "buy" else 1 - slip), 2)


def target_weight(rating: str, current: float, limits: RiskLimits) -> float:
    """The weight a rating asks for. Buy/Overweight never cut, Underweight/Sell never add."""
    cap = limits.max_position_pct
    t = limits.rating_targets
    if rating == "Buy":
        return max(current, cap * t.get("Buy", 1.0))
    if rating == "Overweight":
        return max(current, cap * t.get("Overweight", 0.6))
    if rating == "Underweight":
        return min(current, current * t.get("Underweight", 0.5))
    if rating == "Sell":
        return min(current, cap * t.get("Sell", 0.0))
    return current  # Hold


def _block(rule: str, message: str) -> RiskViolation:
    return RiskViolation(rule=rule, message=message, severity="block")


def _warn(rule: str, message: str) -> RiskViolation:
    return RiskViolation(rule=rule, message=message, severity="warn")


def evaluate(rating: str, ref: MarketRef, book: BookView, limits: RiskLimits, fees: FeeSchedule,
             quantity_override: int | None = None, side: str | None = None) -> RiskCheck:
    """Size and vet the order a rating implies. Pure: no I/O, same inputs, same result.

    ``quantity_override`` and ``side`` re-check a human-edited order: the side
    stays the proposal's, only the size changes, and every rule applies again.
    """
    holding = book.positions.get(ref.ticker)
    equity = book.equity
    price = ref.close
    current_value = holding.quantity * price if holding else 0.0
    current_weight = current_value / equity if equity > 0 else 0.0
    reference = {
        "name": ref.name, "bar_date": ref.bar_date, "close": price, "prev_close": ref.prev_close,
        "limit_up": ref.limit_up, "limit_down": ref.limit_down, "board": ref.board, "is_st": ref.is_st,
        "equity": round(equity, 2), "cash": round(book.cash, 2), "drawdown": round(book.drawdown, 4),
        "held": holding.quantity if holding else 0, "available": holding.available if holding else 0,
    }
    violations: list[RiskViolation] = []
    warnings: list[RiskViolation] = []

    def result(order: OrderProposal | None = None) -> RiskCheck:
        approved = order is not None and order.quantity > 0 and not violations
        return RiskCheck(rating=rating, approved=approved, order=order, violations=violations,
                         warnings=warnings, reference=reference)

    if rating not in TRADEABLE:
        violations.append(_block("unreadable_rating",
                                 f"The decision has no readable rating ({rating}); a person must review it."))
        return result()
    if ref.suspended:
        violations.append(_block("suspended", f"No bar on {ref.trade_date} (latest {ref.bar_date}): "
                                              "suspended or not a trading day."))
        return result()

    target = target_weight(rating, current_weight, limits)
    reference["target_weight"] = round(target, 4)
    reference["current_weight"] = round(current_weight, 4)
    delta_value = (target - current_weight) * equity

    if side is None:
        if abs(delta_value) < price * limits.lot_size * 0.5:
            warnings.append(_warn("no_change", f"{rating}: the position is already at its target weight."))
            return result()
        side = "buy" if delta_value > 0 else "sell"

    if side == "buy":
        exec_price = fill_price("buy", price, fees)
        if quantity_override is not None:
            qty = quantity_override
            if qty % limits.lot_size:
                violations.append(_block("lot_size", f"Buys must be whole lots of {limits.lot_size} shares."))
        else:
            qty = math.floor(delta_value / exec_price / limits.lot_size) * limits.lot_size

        if ref.is_st and limits.block_st:
            violations.append(_block("st_stock", "Buying ST / *ST stocks is disabled."))
        if price >= ref.limit_up:
            violations.append(_block("limit_up", f"Close {price} is at the limit-up price {ref.limit_up}; "
                                                 "a sealed board will not fill a buy."))
        elif price >= ref.limit_up * 0.98:
            warnings.append(_warn("near_limit_up", f"Close {price} is within 2% of limit-up {ref.limit_up}."))
        if book.drawdown >= limits.max_drawdown_pct:
            violations.append(_block("drawdown_breaker",
                                     f"Account drawdown {book.drawdown:.1%} >= {limits.max_drawdown_pct:.0%}: "
                                     "new buys are halted."))
        # Position cap (a human override may not exceed it either).
        max_qty_weight = math.floor(
            (limits.max_position_pct * equity - current_value) / exec_price / limits.lot_size) * limits.lot_size
        if qty > max_qty_weight:
            if quantity_override is not None:
                violations.append(_block("position_limit", f"{qty} shares would exceed the "
                                                          f"{limits.max_position_pct:.0%} per-name limit."))
            else:
                qty = max(0, max_qty_weight)
        # Gross exposure.
        room = limits.max_gross_exposure_pct * equity - book.market_value
        max_qty_gross = math.floor(room / exec_price / limits.lot_size) * limits.lot_size
        if qty > max_qty_gross:
            if quantity_override is not None:
                violations.append(_block("gross_exposure", "The order would exceed the gross exposure limit."))
            else:
                warnings.append(_warn("reduced_for_exposure", "Quantity cut to stay within gross exposure."))
                qty = max(0, max_qty_gross)
        # Cash, fees included.
        spendable = book.cash - limits.min_cash_reserve
        while qty > 0 and qty * exec_price + estimate_fees("buy", qty, exec_price, fees)["total"] > spendable:
            if quantity_override is not None:
                violations.append(_block("insufficient_cash", f"{qty} shares cost more than the "
                                                             f"spendable cash {spendable:,.2f}."))
                break
            qty -= limits.lot_size
            if not any(w.rule == "reduced_for_cash" for w in warnings):
                warnings.append(_warn("reduced_for_cash", "Quantity cut to the cash available."))
        if qty < limits.lot_size and not violations:
            violations.append(_block("below_one_lot", "The sized order is below one 100-share lot "
                                                      "(cash, limits or target too small)."))
    else:
        exec_price = fill_price("sell", price, fees)
        held = holding.quantity if holding else 0
        available = holding.available if holding else 0
        if quantity_override is not None:
            qty = quantity_override
        elif target <= 0:
            qty = held
        else:
            qty = max(1, round(-delta_value / price / limits.lot_size)) * limits.lot_size
            qty = min(qty, held)
        if held == 0:
            violations.append(_block("no_position", f"{rating}: nothing held to sell."))
        if qty > available:
            if available == 0 and held > 0:
                violations.append(_block("t_plus_1", "All shares were bought today; T+1 forbids selling them."))
            elif quantity_override is not None:
                violations.append(_block("t_plus_1", f"Only {available} shares are sellable today (T+1)."))
            else:
                warnings.append(_warn("t_plus_1", f"Sell cut to the {available} shares sellable today (T+1)."))
                qty = available
        if qty % limits.lot_size and qty != held:
            violations.append(_block("lot_size", "Odd lots may only be sold together with the whole position."))
        if price <= ref.limit_down:
            violations.append(_block("limit_down", f"Close {price} is at the limit-down price {ref.limit_down}; "
                                                   "a sealed board will not fill a sell."))

    if book.orders_today >= limits.max_orders_per_day:
        violations.append(_block("order_count", f"{book.orders_today} orders already today "
                                                f"(limit {limits.max_orders_per_day})."))

    qty = max(0, int(qty))
    est = estimate_fees(side, qty, exec_price, fees)
    order = OrderProposal(
        ticker=ref.ticker, side=side, quantity=qty, price=exec_price, notional=round(qty * exec_price, 2),
        est_fees=est["total"], target_weight=round(target, 4), current_weight=round(current_weight, 4))
    return result(order)
