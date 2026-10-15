"""The whole QuantCouncil graph offline: scripted models, in-memory checkpointer and store.

Pins the wiring the platform adds on top of the core: the A-share analyst line-up
(with the capital analyst on local tools), the analysis subgraph, the risk gate,
the human-approval interrupt and its resume, execution, and the event mapping
the SSE feed is built from.
"""

from __future__ import annotations

import copy

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from quantcouncil.api.schemas import Execution
from quantcouncil.config import FeeSchedule, RiskLimits
from quantcouncil.graph import cn_capital_analyst, nodes
from quantcouncil.graph.builder import build_graph
from quantcouncil.graph.core import CouncilCore
from quantcouncil.graph.local_tools import LOCAL_TOOLS
from quantcouncil.graph.runner import EventMapper
from quantcouncil.markets import CN, Instrument, agent_config
from quantcouncil.memory.store import decisions_ns
from quantcouncil.risk import BookView, MarketRef, evaluate
from tests.test_graph_end_to_end import ScriptedModel, _Client, offline  # noqa: F401 (fixture)
from tradingagents.dataflows import router
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.vendors.cn import common
from tradingagents.graph import trading_graph

pytestmark = pytest.mark.unit
TRADE_DATE = "2026-01-09"


class FakeBus:
    def __init__(self):
        self.events = []

    async def publish(self, run_id, type_, data=None):
        self.events.append((str(type_.value if hasattr(type_, "value") else type_), data or {}))
        return str(len(self.events))


@pytest.fixture
def platform(monkeypatch, tmp_path, offline):  # noqa: F811
    monkeypatch.setattr(common.time, "sleep", lambda s: None)
    monkeypatch.setitem(router._CN_SNAPSHOT_BUILDERS, "akshare", lambda *a, **k: "verified snapshot")
    cn_capital_analyst.register(LOCAL_TOOLS)

    ref = MarketRef(ticker="600519.SS", trade_date=TRADE_DATE, bar_date=TRADE_DATE, close=100.0, prev_close=99.0,
                    limit_up=108.9, limit_down=89.1)

    async def fake_check(state, quantity=None, side=None):
        return evaluate(state["final_rating"], ref, BookView(cash=1_000_000, peak_equity=1_000_000),
                        RiskLimits(), FeeSchedule(slippage_bps=0), quantity_override=quantity, side=side)

    fills = []

    async def fake_execute(state):
        order = state["risk_check"]["order"]
        fills.append(order)
        out = Execution(order_id="o1", ticker=order["ticker"], side=order["side"], quantity=order["quantity"],
                        price=order["price"], fees={"total": 5.0}, cash_after=0.0, status="filled")
        return {"execution": out.model_dump(mode="json")}

    monkeypatch.setattr(nodes, "_check", fake_check)
    monkeypatch.setattr(nodes, "execute", fake_execute)

    cfg = agent_config(Instrument("600519.SS", CN), data_dir=tmp_path)
    cfg.update(max_debate_rounds=1, max_risk_discuss_rounds=1)
    monkeypatch.setattr(trading_graph, "create_tier_client",
                        lambda config, tier, **k: _Client(ScriptedModel(structured=True)))
    core = CouncilCore(selected_analysts=["market", "cn_capital", "news", "fundamentals"], config=copy.deepcopy(cfg))
    core.store = InMemoryStore()
    graph = build_graph(core, checkpointer=InMemorySaver(), store=core.store)
    return core, graph, fills


async def _drive(core, graph, graph_input, config, bus):
    mapper = EventMapper("run-1", bus)
    with run_config(core.config):
        async for ns, mode, chunk in graph.astream(graph_input, config, subgraphs=True,
                                                   stream_mode=["tasks", "updates", "messages", "custom"]):
            await mapper.handle(ns, mode, chunk)
    await mapper.flush_tokens()


async def test_a_run_pauses_for_approval_then_books_the_order(platform):
    core, graph, fills = platform
    config = {"configurable": {"thread_id": "run-1"}, "recursion_limit": 300}
    init = core.create_run_state("600519.SS", TRADE_DATE)
    init.update(run_id="run-1", market=CN, account_id="t", auto_approve=False,
                risk_check=None, approval=None, execution=None)
    bus = FakeBus()

    await _drive(core, graph, init, config, bus)
    state = await graph.aget_state(config)
    assert state.next == (nodes.HUMAN_APPROVAL,)
    assert state.values["sentiment_report"]  # the A-share capital analyst filled the sentiment seat
    order = state.values["risk_check"]["order"]
    assert order["side"] == "buy" and order["quantity"] % 100 == 0 and not fills

    types = [t for t, _ in bus.events]
    for expected in ("report", "debate", "plan", "decision", "risk_check", "approval_required", "tool_call"):
        assert expected in types, expected
    reports = {d["key"] for t, d in bus.events if t == "report"}
    assert reports == {"market_report", "sentiment_report", "news_report", "fundamentals_report"}
    started = {d["node"] for t, d in bus.events if t == "node" and d["phase"] == "start"}
    assert {"Market Analyst", "Sentiment Analyst", "Portfolio Manager", "Risk Gate", "Human Approval"} <= started

    # A resize that breaks the lot rule is refused and asked again; a valid one goes through.
    await _drive(core, graph, Command(resume={"action": "modify", "quantity": 250}), config, bus)
    state = await graph.aget_state(config)
    assert state.next == (nodes.HUMAN_APPROVAL,) and not state.values["approval"]["accepted"]

    await _drive(core, graph, Command(resume={"action": "modify", "quantity": 300, "comment": "smaller"}),
                 config, bus)
    state = await graph.aget_state(config)
    assert not state.next
    assert fills and fills[0]["quantity"] == 300
    assert state.values["execution"]["status"] == "filled"
    decisions = await core.store.asearch(decisions_ns("600519.SS"))
    assert decisions and decisions[0].value["rating"] == "Overweight"


async def test_rejection_books_nothing(platform):
    core, graph, fills = platform
    config = {"configurable": {"thread_id": "run-2"}, "recursion_limit": 300}
    init = core.create_run_state("600519.SS", TRADE_DATE)
    init.update(run_id="run-2", market=CN, account_id="t", auto_approve=False,
                risk_check=None, approval=None, execution=None)
    bus = FakeBus()
    await _drive(core, graph, init, config, bus)
    await _drive(core, graph, Command(resume={"action": "reject", "comment": "no"}), config, bus)
    state = await graph.aget_state(config)
    assert not state.next and not fills
    assert state.values["approval"]["action"] == "reject" and state.values["execution"] is None


async def test_auto_approve_skips_the_interrupt(platform):
    core, graph, fills = platform
    config = {"configurable": {"thread_id": "run-3"}, "recursion_limit": 300}
    init = core.create_run_state("600519.SS", TRADE_DATE)
    init.update(run_id="run-3", market=CN, account_id="t", auto_approve=True,
                risk_check=None, approval=None, execution=None)
    await _drive(core, graph, init, config, FakeBus())
    state = await graph.aget_state(config)
    assert not state.next and len(fills) == 1
