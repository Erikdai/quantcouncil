"""Deterministic pre-trade risk: A-share market rules and book limits."""

from __future__ import annotations

from quantcouncil.risk.engine import (
    BookView,
    Holding,
    MarketRef,
    estimate_fees,
    evaluate,
    fill_price,
    target_weight,
)


def market_ref_for(ticker: str, trade_date: str) -> MarketRef:
    """Unadjusted reference prices and limits for an A-share on ``trade_date`` (blocking I/O)."""
    from tradingagents.dataflows.vendors.cn import limit_prices, parse_a_share  # noqa: PLC0415
    from tradingagents.dataflows.vendors.cn.fundamentals import get_cn_profile  # noqa: PLC0415
    from tradingagents.dataflows.vendors.cn.market import latest_bar  # noqa: PLC0415

    bar = latest_bar(ticker, trade_date)
    try:
        name = "".join((get_cn_profile(ticker).get("A股简称") or "").split()) or None
    except Exception:  # noqa: BLE001 — the name only feeds the ST check and display
        name = None
    is_st = bool(name and "ST" in name.upper())
    up, down = limit_prices(ticker, bar["prev_close"], is_st)
    return MarketRef(ticker=ticker, trade_date=trade_date, bar_date=bar["date"], close=bar["close"],
                     prev_close=bar["prev_close"], limit_up=up, limit_down=down, is_st=is_st,
                     board=parse_a_share(ticker).board, name=name)


__all__ = ["BookView", "Holding", "MarketRef", "estimate_fees", "evaluate", "fill_price", "market_ref_for",
           "target_weight"]
