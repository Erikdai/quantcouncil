import pytest

from finagent.config import FeeSchedule, RiskLimits
from finagent.risk import BookView, Holding, MarketRef, estimate_fees, evaluate, fill_price

pytestmark = pytest.mark.unit

LIMITS = RiskLimits(max_position_pct=0.10, max_gross_exposure_pct=0.95, min_cash_reserve=1000,
                    max_drawdown_pct=0.15, max_orders_per_day=20, block_st=True, lot_size=100)
FEES = FeeSchedule(slippage_bps=0)


def ref(close=100.0, prev=100.0, *, st=False, bar_date="2026-10-14", ticker="600519.SS"):
    return MarketRef(ticker=ticker, trade_date="2026-10-14", bar_date=bar_date, close=close, prev_close=prev,
                     limit_up=round(prev * 1.1, 2), limit_down=round(prev * 0.9, 2), is_st=st)


def book(cash=1_000_000.0, positions=None, peak=None, orders_today=0):
    b = BookView(cash=cash, peak_equity=0, positions=positions or {}, orders_today=orders_today)
    b.peak_equity = peak if peak is not None else b.equity
    return b


def rules(check):
    return {v.rule for v in check.violations}


def test_buy_is_sized_to_the_position_cap_in_whole_lots():
    check = evaluate("Buy", ref(close=123.45, prev=123.0), book(), LIMITS, FEES)
    assert check.approved
    order = check.order
    assert order.side == "buy" and order.quantity % 100 == 0
    assert order.quantity * order.price <= 0.10 * 1_000_000
    assert (order.quantity + 100) * order.price > 0.10 * 1_000_000 - 1  # the largest lot count that fits


def test_overweight_targets_sixty_percent_of_the_cap():
    check = evaluate("Overweight", ref(close=10.0), book(), LIMITS, FEES)
    assert check.order.quantity == 6000  # 6% of 1,000,000 at 10.00


def test_buying_at_limit_up_is_blocked():
    check = evaluate("Buy", ref(close=110.0, prev=100.0), book(), LIMITS, FEES)
    assert not check.approved and "limit_up" in rules(check)


def test_near_limit_up_is_a_warning_only():
    check = evaluate("Buy", ref(close=108.5, prev=100.0), book(), LIMITS, FEES)
    assert check.approved and "near_limit_up" in {w.rule for w in check.warnings}


def test_st_stocks_cannot_be_bought():
    check = evaluate("Buy", ref(st=True), book(), LIMITS, FEES)
    assert "st_stock" in rules(check)


def test_suspended_stock_has_no_order():
    check = evaluate("Buy", ref(bar_date="2026-10-13"), book(), LIMITS, FEES)
    assert not check.approved and check.order is None and "suspended" in rules(check)


def test_unreadable_rating_needs_a_human():
    check = evaluate("REVIEW", ref(), book(), LIMITS, FEES)
    assert "unreadable_rating" in rules(check) and check.order is None


def test_hold_proposes_nothing():
    held = {"600519.SS": Holding(quantity=500, available=500, avg_cost=90, last_price=100)}
    check = evaluate("Hold", ref(), book(cash=950_000, positions=held), LIMITS, FEES)
    assert not check.approved and check.order is None


def test_t_plus_one_blocks_selling_shares_bought_today():
    held = {"600519.SS": Holding(quantity=1000, available=0, avg_cost=100, last_price=100)}
    check = evaluate("Sell", ref(), book(cash=900_000, positions=held), LIMITS, FEES)
    assert "t_plus_1" in rules(check)


def test_t_plus_one_trims_a_sell_to_the_sellable_shares():
    held = {"600519.SS": Holding(quantity=1000, available=400, avg_cost=100, last_price=100)}
    check = evaluate("Sell", ref(), book(cash=900_000, positions=held), LIMITS, FEES)
    assert check.approved and check.order.quantity == 400
    assert "t_plus_1" in {w.rule for w in check.warnings}


def test_underweight_halves_the_position_in_whole_lots():
    held = {"600519.SS": Holding(quantity=1000, available=1000, avg_cost=100, last_price=100)}
    slipped = FeeSchedule(slippage_bps=5)
    check = evaluate("Underweight", ref(), book(cash=900_000, positions=held), LIMITS, slipped)
    assert check.approved and check.order.side == "sell" and check.order.quantity == 500


def test_sell_all_includes_the_odd_lot():
    held = {"600519.SS": Holding(quantity=1050, available=1050, avg_cost=100, last_price=100)}
    check = evaluate("Sell", ref(), book(cash=900_000, positions=held), LIMITS, FEES)
    assert check.approved and check.order.side == "sell" and check.order.quantity == 1050


def test_selling_at_limit_down_is_blocked():
    held = {"600519.SS": Holding(quantity=1000, available=1000, avg_cost=100, last_price=90)}
    check = evaluate("Sell", ref(close=90.0, prev=100.0), book(cash=900_000, positions=held), LIMITS, FEES)
    assert "limit_down" in rules(check)


def test_buys_are_cut_to_the_cash_on_hand():
    check = evaluate("Buy", ref(close=30.0, prev=30.0), book(cash=20_000.0, peak=20_000.0), LIMITS, FEES)
    # 10% of 20k equity is 2,000 -> 66 shares at 30: below one lot.
    assert "below_one_lot" in rules(check)
    rich = BookView(cash=30_000.0, peak_equity=1_030_000.0,
                    positions={"000001.SZ": Holding(quantity=100_000, available=100_000, avg_cost=10,
                                                    last_price=10)})
    no_gross_cap = LIMITS.model_copy(update={"max_gross_exposure_pct": 1.0})
    check = evaluate("Buy", ref(close=50.0, prev=50.0), rich, no_gross_cap, FEES)
    assert check.order.quantity * 50 + check.order.est_fees <= 30_000 - 1000
    assert "reduced_for_cash" in {w.rule for w in check.warnings}


def test_drawdown_breaker_halts_new_buys():
    check = evaluate("Buy", ref(), book(cash=800_000, peak=1_000_000), LIMITS, FEES)
    assert "drawdown_breaker" in rules(check)


def test_order_count_cap():
    check = evaluate("Buy", ref(), book(orders_today=20), LIMITS, FEES)
    assert "order_count" in rules(check)


def test_human_resize_is_rechecked():
    ok = evaluate("Buy", ref(), book(), LIMITS, FEES, quantity_override=300, side="buy")
    assert ok.approved and ok.order.quantity == 300
    odd = evaluate("Buy", ref(), book(), LIMITS, FEES, quantity_override=250, side="buy")
    assert "lot_size" in rules(odd)
    too_big = evaluate("Buy", ref(), book(), LIMITS, FEES, quantity_override=5000, side="buy")
    assert "position_limit" in rules(too_big)


def test_fees_follow_the_a_share_schedule():
    fees = FeeSchedule()
    small = estimate_fees("buy", 100, 10.0, fees)
    assert small["commission"] == 5.0 and small["stamp_duty"] == 0.0  # minimum commission, no duty on buys
    sell = estimate_fees("sell", 10_000, 100.0, fees)
    assert sell["commission"] == 250.0 and sell["stamp_duty"] == 500.0 and sell["transfer_fee"] == 10.0
    assert sell["total"] == 760.0


def test_paper_fills_pay_slippage():
    fees = FeeSchedule(slippage_bps=10)
    assert fill_price("buy", 100.0, fees) == 100.1
    assert fill_price("sell", 100.0, fees) == 99.9
