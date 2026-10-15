"""Load the cn-market MCP tools, with interceptors for point-in-time dates and retries."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from mcp.types import CallToolResult, TextContent

from finagent.config import get_settings
from tradingagents.dataflows.date_window import as_of, as_of_window

logger = logging.getLogger(__name__)

SERVER_NAME = "cn-market"


def _trade_date(request: MCPToolCallRequest) -> str | None:
    state = getattr(request.runtime, "state", None)
    if isinstance(state, dict):
        return state.get("trade_date") or None
    return getattr(state, "trade_date", None) if state is not None else None


class PointInTimeInterceptor:
    """Clamp dated arguments to the run's trade date."""

    async def __call__(self, request: MCPToolCallRequest, handler):
        trade_date = _trade_date(request)
        if not trade_date:
            return await handler(request)
        args = dict(request.args)
        if "start_date" in args and "end_date" in args:
            try:
                args["start_date"], args["end_date"] = as_of_window(args["start_date"], args["end_date"], trade_date)
            except ValueError:
                args["end_date"] = trade_date
        if "as_of_date" in args or request.name in _DATED_TOOLS:
            args["as_of_date"] = as_of(args.get("as_of_date"), trade_date) or trade_date
        if args != request.args:
            logger.debug("PIT clamp %s: %s -> %s", request.name, request.args, args)
            request = request.override(args=args)
        return await handler(request)


class RetryInterceptor:
    def __init__(self, attempts: int = 3, backoff: float = 0.5):
        self.attempts, self.backoff = attempts, backoff

    async def __call__(self, request: MCPToolCallRequest, handler):
        last: Exception | None = None
        for attempt in range(self.attempts):
            try:
                return await handler(request)
            except Exception as exc:  # noqa: BLE001 — transport errors vary by transport
                last = exc
                await asyncio.sleep(self.backoff * (2 ** attempt))
        logger.warning("MCP tool %s failed after %d attempts: %s", request.name, self.attempts, last)
        return CallToolResult(content=[TextContent(
            type="text", text=f"DATA_UNAVAILABLE: tool {request.name} could not be reached ({last}).")],
            isError=True)


# Tools that take as_of_date even when the model omits it.
_DATED_TOOLS = {
    "get_market_snapshot", "get_technical_indicator", "get_company_fundamentals", "get_financial_statement",
    "get_top_shareholders", "get_market_telegraph", "get_china_macro", "get_dragon_tiger", "get_margin_trading",
    "get_market_breadth", "get_research_reports", "get_fund_flow",
}


def connections(url: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    return {SERVER_NAME: {"transport": "streamable_http", "url": url or settings.mcp_url, "timeout": 120}}


def make_client(conn: dict[str, Any] | None = None) -> MultiServerMCPClient:
    return MultiServerMCPClient(conn or connections(),
                                tool_interceptors=[PointInTimeInterceptor(), RetryInterceptor()])


_tools_cache: list[BaseTool] | None = None


async def load_tools(names: list[str] | None = None, *, refresh: bool = False,
                     conn: dict[str, Any] | None = None) -> list[BaseTool]:
    """The server's tools as LangChain tools (cached per process), optionally filtered by name."""
    global _tools_cache
    if _tools_cache is None or refresh or conn is not None:
        tools = await make_client(conn).get_tools(server_name=SERVER_NAME)
        if conn is not None:
            return [t for t in tools if names is None or t.name in names]
        _tools_cache = tools
    return [t for t in _tools_cache if names is None or t.name in names]
