from types import SimpleNamespace

import pytest
from langchain_mcp_adapters.interceptors import MCPToolCallRequest

from finagent.markets import CN, US, agent_config, core_analysts, resolve_instrument
from finagent.mcp_client import PointInTimeInterceptor
from finagent.skills import get_skill, list_skills, load_skill, skills_index_prompt

pytestmark = pytest.mark.unit


# --- MCP point-in-time interceptor -------------------------------------------------------

async def _intercept(name, args, trade_date):
    runtime = SimpleNamespace(state={"trade_date": trade_date}) if trade_date else None
    seen = {}

    async def handler(req):
        seen.update(req.args)
        return "ok"

    await PointInTimeInterceptor()(MCPToolCallRequest(name=name, args=args, server_name="cn-market",
                                                      runtime=runtime), handler)
    return seen


async def test_future_as_of_dates_are_clamped_to_the_trade_date():
    seen = await _intercept("get_dragon_tiger", {"symbol": "600519", "as_of_date": "2026-10-14"}, "2026-06-01")
    assert seen["as_of_date"] == "2026-06-01"


async def test_a_missing_as_of_date_is_filled_in():
    seen = await _intercept("get_market_breadth", {}, "2026-06-01")
    assert seen["as_of_date"] == "2026-06-01"


async def test_windows_are_moved_back_not_truncated():
    seen = await _intercept("get_company_news", {"symbol": "600519", "start_date": "2026-10-01",
                                                 "end_date": "2026-10-14"}, "2026-06-01")
    assert seen["end_date"] == "2026-06-01" and seen["start_date"] == "2026-05-19"


async def test_outside_a_run_arguments_pass_through():
    seen = await _intercept("get_dragon_tiger", {"symbol": "600519", "as_of_date": "2026-10-14"}, None)
    assert seen["as_of_date"] == "2026-10-14"


# --- Skills -------------------------------------------------------------------------------

def test_repo_skills_parse():
    names = {s.name for s in list_skills()}
    assert {"a-share-trading-rules", "earnings-red-flags", "dragon-tiger-reading"} <= names
    assert all(s.description for s in list_skills())
    assert "T+1" in get_skill("a-share-trading-rules").body
    assert "load_skill" in skills_index_prompt()


def test_load_skill_tool():
    assert "龙虎榜" in load_skill.invoke({"name": "dragon-tiger-reading"})
    assert "No skill named" in load_skill.invoke({"name": "nope"})


# --- Markets ------------------------------------------------------------------------------

def test_resolve_and_configure_an_a_share_run(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_OUTPUT_LANGUAGE", raising=False)
    inst = resolve_instrument("sz000001")
    assert (inst.ticker, inst.market) == ("000001.SZ", CN)
    cfg = agent_config(inst, data_dir="/tmp/x")
    assert cfg["data_vendors"]["core_stock_apis"].startswith("akshare")
    assert cfg["benchmark_map"][".SZ"] == "000300.SS"
    assert cfg["output_language"] == "Simplified Chinese"
    assert cfg["llm_max_retries"] == 6


def test_us_runs_keep_the_core_defaults():
    inst = resolve_instrument("nvda")
    assert (inst.ticker, inst.market) == ("NVDA", US)
    assert agent_config(inst)["data_vendors"]["core_stock_apis"] == "yfinance"


def test_analyst_names_map_per_market():
    assert core_analysts(CN, ["market", "sentiment"]) == ["market", "cn_capital"]
    assert core_analysts(US, ["sentiment"]) == ["social"]
    with pytest.raises(ValueError):
        core_analysts(CN, ["astrology"])


def test_message_text_from_any_provider():
    from finagent.messages import content_text  # noqa: PLC0415

    assert content_text("plain") == "plain"
    blocks = [{"type": "text", "text": "Hel"}, {"type": "tool_use", "id": "t1"}, {"type": "text", "text": "lo"}]
    assert content_text(blocks) == "Hello"
    assert content_text(None) == ""
