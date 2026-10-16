"""cn-market MCP server: A-share data tools, research search, and skills as prompts/resources.

    python -m quantcouncil.mcp_server                                        # stdio
    python -m quantcouncil.mcp_server --transport streamable-http --port 8001
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Callable
from datetime import date
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse

import quantcouncil
from quantcouncil.markets import agent_config, resolve_instrument
from quantcouncil.skills import get_skill, list_skills
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.errors import NoMarketDataError, VendorError
from tradingagents.dataflows.vendors import sec_edgar
from tradingagents.dataflows.vendors.cn import (
    canonical_symbol,
    capital,
    fundamentals,
    is_a_share,
    macro,
    market,
    news,
)
from tradingagents.dataflows.vendors.yahoo import (
    fundamentals as us_fundamentals,
    market as us_market,
    news as us_news,
)
from tradingagents.dataflows.vendors.yahoo.snapshot import build_verified_market_snapshot

logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="cn-market",
    instructions=(
        "A-share and US stock/ETF research data. Symbols accept 600519, 600519.SH, sz000001, AAPL, NVDA, BRK-B. "
        "Shared price, indicator, fundamentals, statements and company news tools route by symbol. "
        "Capital-flow, China macro and broker-report tools cover A-shares only. "
        "Pass the analysis date as as_of_date. US statements use SEC filing dates; Yahoo profiles are live-only "
        "and withheld for historical dates. Yahoo news has limited recent coverage, not a full archive. "
        "Results are markdown; a line starting with "
        "DATA_UNAVAILABLE or NO_DATA means the data could not be served - say so, never estimate it."
    ),
    stateless_http=True,
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


async def _call(name: str, fn: Callable[..., str], *args: Any) -> str:
    """Run a blocking vendor call off the event loop and turn vendor errors into sentinels."""
    try:
        return await asyncio.to_thread(fn, *args)
    except NoMarketDataError as exc:
        return f"NO_DATA: {name}: {exc}. Do not estimate or fabricate values."
    except VendorError as exc:
        return f"DATA_UNAVAILABLE: {name}: the data source could not answer ({exc}). This says nothing about the stock."
    except ValueError as exc:
        return f"INVALID_ARGUMENT: {name}: {exc}"
    except Exception as exc:  # noqa: BLE001 — answer with a sentinel rather than a protocol error
        logger.exception("tool %s failed", name)
        return f"DATA_UNAVAILABLE: {name}: {type(exc).__name__}."


def _symbol(symbol: str) -> str:
    if not is_a_share(symbol):
        raise ValueError(f"{symbol!r} is not an A-share code")
    return canonical_symbol(symbol)


def _today() -> str:
    return date.today().isoformat()


async def _market_call(name: str, symbol: str, cn_fn: Callable, us_fn: Callable, *args: Any) -> str:
    """Keep each threaded request's vendor/cache settings scoped to its market."""
    def fetch() -> str:
        instrument = resolve_instrument(symbol)
        with run_config(agent_config(instrument)):
            return (cn_fn if instrument.is_cn else us_fn)(instrument.ticker, *args)

    return await _call(name, fetch)


# --- Market -------------------------------------------------------------------------

@mcp.tool(annotations=READ_ONLY)
async def get_stock_bars(symbol: str, start_date: str, end_date: str) -> str:
    """Daily adjusted OHLCV for A-shares or US stocks/ETFs between two dates (YYYY-MM-DD)."""
    return await _market_call("get_stock_bars", symbol, market.get_cn_stock_data,
                              us_market.get_YFin_data_online, start_date, end_date)


@mcp.tool(annotations=READ_ONLY)
async def get_market_snapshot(symbol: str, as_of_date: str) -> str:
    """Verified latest bar, common indicators (SMA/EMA/RSI/MACD/Bollinger/ATR) and recent closes as of a date.
    Treat it as the source of truth for exact price and indicator values."""
    return await _market_call("get_market_snapshot", symbol, market.build_cn_snapshot,
                              build_verified_market_snapshot, as_of_date, 20)


@mcp.tool(annotations=READ_ONLY)
async def get_technical_indicator(symbol: str, indicator: str, as_of_date: str, look_back_days: int = 30) -> str:
    """One technical indicator series. indicator: close_50_sma, close_200_sma, close_10_ema, macd, macds,
    macdh, rsi, boll, boll_ub, boll_lb, atr, vwma, mfi."""
    return await _market_call("get_technical_indicator", symbol, market.get_cn_indicator_window,
                              us_market.get_stock_stats_indicators_window, indicator, as_of_date, look_back_days)


# --- Fundamentals ---------------------------------------------------------------------

@mcp.tool(annotations=READ_ONLY)
async def get_company_fundamentals(symbol: str, as_of_date: str) -> str:
    """A-share historical fundamentals, or Yahoo US company profile/valuation (live only).
    US profiles are withheld for past dates; use get_financial_statement for SEC filing-date data."""
    return await _market_call("get_company_fundamentals", symbol, fundamentals.get_cn_fundamentals,
                              us_fundamentals.get_fundamentals, as_of_date)


@mcp.tool(annotations=READ_ONLY)
async def get_financial_statement(symbol: str, statement: Literal["income", "balance", "cashflow"],
                                  as_of_date: str, freq: Literal["quarterly", "annual"] = "quarterly") -> str:
    """Statements published by as_of_date: A-share disclosures or US SEC EDGAR as filed.
    Each response labels its units; US statements are not in CNY 100M. No Yahoo statement substitution."""
    fn = {"income": fundamentals.get_cn_income_statement, "balance": fundamentals.get_cn_balance_sheet,
          "cashflow": fundamentals.get_cn_cashflow}[statement]
    us_fn = {"income": sec_edgar.get_income_statement, "balance": sec_edgar.get_balance_sheet,
             "cashflow": sec_edgar.get_cashflow}[statement]
    return await _market_call("get_financial_statement", symbol, fn, us_fn, freq, as_of_date)


@mcp.tool(annotations=READ_ONLY)
async def get_top_shareholders(symbol: str, as_of_date: str) -> str:
    """Top-10 float shareholders and their changes for the latest period disclosed by as_of_date."""
    return await _call("get_top_shareholders", fundamentals.get_cn_insider_transactions, _symbol(symbol),
                       as_of_date)


# --- News & macro ---------------------------------------------------------------------

@mcp.tool(annotations=READ_ONLY)
async def get_company_news(symbol: str, start_date: str, end_date: str) -> str:
    """Company headlines/summaries: Eastmoney for A-shares, Yahoo for US stocks.
    US feed is a recent sample, not a historical archive; missing coverage is not neutral sentiment."""
    return await _market_call("get_company_news", symbol, news.get_cn_news,
                              us_news.get_news_yfinance, start_date, end_date)


@mcp.tool(annotations=READ_ONLY)
async def get_market_telegraph(as_of_date: str, look_back_days: int = 1, limit: int = 30) -> str:
    """Market-moving headlines from the Cailian Press telegraph."""
    return await _call("get_market_telegraph", news.get_cn_global_news, as_of_date, look_back_days, limit)


@mcp.tool(annotations=READ_ONLY)
async def get_china_macro(indicator: Literal["cn_lpr", "cn_m2", "cn_cpi", "cn_pmi"], as_of_date: str,
                          look_back_days: int = 365) -> str:
    """China macro series as published by as_of_date: LPR, M2/M1 growth, CPI YoY, manufacturing PMI."""
    return await _call("get_china_macro", macro.get_cn_macro, indicator, as_of_date, look_back_days)


# --- Capital flow & sentiment ---------------------------------------------------------

@mcp.tool(annotations=READ_ONLY)
async def get_dragon_tiger(symbol: str, as_of_date: str, look_back_days: int = 30) -> str:
    """Dragon-Tiger list entries: abnormal-move days with top seats' net buying."""
    return await _call("get_dragon_tiger", capital.get_dragon_tiger, _symbol(symbol), as_of_date, look_back_days)


@mcp.tool(annotations=READ_ONLY)
async def get_margin_trading(symbol: str, as_of_date: str, sessions: int = 5) -> str:
    """Margin financing balance and buys over the last sessions to as_of_date."""
    return await _call("get_margin_trading", capital.get_margin_trading, _symbol(symbol), as_of_date, sessions)


@mcp.tool(annotations=READ_ONLY)
async def get_market_breadth(as_of_date: str) -> str:
    """Whole-market sentiment on a day: limit-up / limit-down counts, streak height, broken boards, hot sectors."""
    return await _call("get_market_breadth", capital.get_market_breadth, as_of_date)


@mcp.tool(annotations=READ_ONLY)
async def get_research_reports(symbol: str, as_of_date: str, look_back_days: int = 90) -> str:
    """Sell-side research published in the window: institutions, ratings, EPS forecasts and consensus."""
    return await _call("get_research_reports", capital.get_research_reports, _symbol(symbol), as_of_date,
                       look_back_days)


@mcp.tool(annotations=READ_ONLY)
async def get_fund_flow(symbol: str, as_of_date: str, sessions: int = 10) -> str:
    """Main-force net inflow by session (Eastmoney; may be unavailable outside mainland China)."""
    return await _call("get_fund_flow", capital.get_individual_fund_flow, _symbol(symbol), as_of_date, sessions)


# --- Research corpus (RAG) --------------------------------------------------------------

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def search_research_docs(query: str, symbol: str | None = None, as_of_date: str | None = None,
                               k: int = 6) -> str:
    """Hybrid search (vector + keyword + rerank) over ingested exchange announcements and broker reports.
    Returns numbered passages to cite as [n]; only documents published by as_of_date are searched."""
    from quantcouncil.rag.retriever import format_hits, search  # noqa: PLC0415 — needs the database

    try:
        hits = await search(query, ticker=resolve_instrument(symbol).ticker if symbol else None,
                            as_of=date.fromisoformat(as_of_date) if as_of_date else None, k=min(max(k, 1), 12))
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_research_docs failed: %s", exc)
        return f"DATA_UNAVAILABLE: research search failed ({type(exc).__name__})."
    return format_hits(hits)


# --- Skills as prompts and resources ---------------------------------------------------------

def _register_skill_prompts() -> None:
    for skill in list_skills():
        def make(s=skill):
            def prompt() -> str:
                return s.body
            return prompt
        mcp.prompt(name=f"skill-{skill.name}", description=skill.description)(make())


@mcp.resource("skill://{name}", mime_type="text/markdown", description="An Agent Skill's SKILL.md body")
def skill_resource(name: str) -> str:
    skill = get_skill(name)
    return skill.body if skill else f"No skill named {name}"


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "cn-market", "version": quantcouncil.__version__,
                         "tools": len(await mcp.list_tools()), "skills": len(list_skills())})


_register_skill_prompts()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="cn-market MCP server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http", "sse"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    mcp.settings.host, mcp.settings.port = args.host, args.port
    if args.host not in ("127.0.0.1", "localhost"):
        # Behind docker/k8s networking the Host header is the service name; DNS-rebinding
        # protection is for servers exposed to browsers, which this one is not.
        mcp.settings.transport_security = None
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
