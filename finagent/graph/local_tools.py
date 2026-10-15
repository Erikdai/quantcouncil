"""In-process fallbacks for the cn-market MCP tools, used when the MCP server is unreachable."""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from tradingagents.dataflows.date_window import as_of, as_of_window
from tradingagents.dataflows.errors import NoMarketDataError, VendorError
from tradingagents.dataflows.vendors.cn import capital, news

Sym = Annotated[str, InjectedState("company_of_interest")]
TradeDate = Annotated[str, InjectedState("trade_date")]


def _safe(name, fn, *args) -> str:
    try:
        return fn(*args)
    except NoMarketDataError as exc:
        return f"NO_DATA: {name}: {exc}. Do not estimate or fabricate values."
    except VendorError as exc:
        return f"DATA_UNAVAILABLE: {name}: the data source could not answer ({exc})."
    except Exception as exc:  # noqa: BLE001 — a tool must answer, never raise into the graph
        return f"DATA_UNAVAILABLE: {name}: {type(exc).__name__}: {exc}"


@tool
def get_dragon_tiger(symbol: Sym, trade_date: TradeDate, as_of_date: str = "", look_back_days: int = 30) -> str:
    """Dragon-Tiger list entries: abnormal-move days with top seats' net buying."""
    return _safe("get_dragon_tiger", capital.get_dragon_tiger, symbol, as_of(as_of_date, trade_date) or trade_date,
                 look_back_days)


@tool
def get_margin_trading(symbol: Sym, trade_date: TradeDate, as_of_date: str = "", sessions: int = 5) -> str:
    """Margin financing balance and buys over the last sessions to as_of_date."""
    return _safe("get_margin_trading", capital.get_margin_trading, symbol,
                 as_of(as_of_date, trade_date) or trade_date, sessions)


@tool
def get_market_breadth(trade_date: TradeDate, as_of_date: str = "") -> str:
    """Whole-market sentiment on a day: limit-up / limit-down counts, streak height, broken boards, hot sectors."""
    return _safe("get_market_breadth", capital.get_market_breadth, as_of(as_of_date, trade_date) or trade_date)


@tool
def get_research_reports(symbol: Sym, trade_date: TradeDate, as_of_date: str = "", look_back_days: int = 90) -> str:
    """Sell-side research published in the window: institutions, ratings, EPS forecasts and consensus."""
    return _safe("get_research_reports", capital.get_research_reports, symbol,
                 as_of(as_of_date, trade_date) or trade_date, look_back_days)


@tool
def get_fund_flow(symbol: Sym, trade_date: TradeDate, as_of_date: str = "", sessions: int = 10) -> str:
    """Main-force net inflow by session (may be unavailable outside mainland China)."""
    return _safe("get_fund_flow", capital.get_individual_fund_flow, symbol,
                 as_of(as_of_date, trade_date) or trade_date, sessions)


@tool
def get_company_news(symbol: Sym, trade_date: TradeDate, start_date: str, end_date: str) -> str:
    """Company news headlines and summaries (Eastmoney) in a date window."""
    try:
        start_date, end_date = as_of_window(start_date, end_date, trade_date)
    except ValueError as exc:
        return str(exc)
    return _safe("get_company_news", news.get_cn_news, symbol, start_date, end_date)


@tool
def get_market_telegraph(trade_date: TradeDate, as_of_date: str = "", look_back_days: int = 1) -> str:
    """Market-moving headlines from the Cailian Press telegraph."""
    return _safe("get_market_telegraph", news.get_cn_global_news, as_of(as_of_date, trade_date) or trade_date,
                 look_back_days, 30)


LOCAL_TOOLS = [get_dragon_tiger, get_margin_trading, get_market_breadth, get_research_reports, get_fund_flow,
               get_company_news, get_market_telegraph]
