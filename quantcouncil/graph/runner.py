"""Drive a run's graph, map its stream to run events on Redis, and persist the results."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.types import Command

from quantcouncil import llm_settings
from quantcouncil.api.schemas import RunEventType as E, RunStatus
from quantcouncil.config import get_settings
from quantcouncil.db import session_scope
from quantcouncil.db.models import Run
from quantcouncil.events import EventBus
from quantcouncil.graph import nodes
from quantcouncil.graph.builder import build_graph
from quantcouncil.graph.core import CouncilCore, get_core
from quantcouncil.markets import Instrument
from quantcouncil.messages import content_text
from quantcouncil.observability import tracing
from quantcouncil.portfolio import ledger
from quantcouncil.runtime import get_runtime
from tradingagents.agents.rating import run_rating
from tradingagents.dataflows.config import run_config
from tradingagents.portfolio import PortfolioContext, Position

logger = logging.getLogger(__name__)

ANALYST_NODES = {"Market Analyst", "Sentiment Analyst", "News Analyst", "Fundamentals Analyst"}
DEBATE_NODES = {"Bull Researcher", "Bear Researcher"}
RISK_NODES = {"Aggressive Analyst": "current_aggressive_response",
              "Conservative Analyst": "current_conservative_response",
              "Neutral Analyst": "current_neutral_response"}
PIPELINE_NODES = (ANALYST_NODES | DEBATE_NODES | set(RISK_NODES)
                  | {"Memory Log", "Research Manager", "Trader", "Portfolio Manager",
                     nodes.RISK_GATE, nodes.HUMAN_APPROVAL, nodes.EXECUTE, nodes.RECORD})
REPORT_TITLES = {"market_report": "Market analysis", "sentiment_report": "Capital and sentiment",
                 "news_report": "News and macro", "fundamentals_report": "Fundamentals"}
INNER_NODES = {"agent", "tools", "wrap_up"}


def _names(ns: tuple[str, ...]) -> list[str]:
    return [part.split(":", 1)[0] for part in ns]


def _label(ns: tuple[str, ...], node: str | None) -> str | None:
    """The pipeline node an event belongs to (an analyst's inner agent/tools map to the analyst)."""
    if node in PIPELINE_NODES:
        return node
    for name in reversed(_names(ns)):
        if name in PIPELINE_NODES:
            return name
    return None


class EventMapper:
    TOKEN_FLUSH_CHARS = 160
    TOKEN_FLUSH_SECONDS = 0.35

    def __init__(self, run_id: str, bus: EventBus):
        self.run_id, self.bus = run_id, bus
        self._tokens: dict[str, list[str]] = {}
        self._last_flush = time.monotonic()
        self.milestones: dict[str, Any] = {}

    async def emit(self, type_: E, data: dict | None = None) -> None:
        await self.bus.publish(self.run_id, type_, data or {})

    async def flush_tokens(self, only: str | None = None) -> None:
        for node in list(self._tokens):
            if only and node != only:
                continue
            text = "".join(self._tokens.pop(node))
            if text:
                await self.emit(E.token, {"node": node, "text": text})
        self._last_flush = time.monotonic()

    async def handle(self, ns: tuple[str, ...], mode: str, chunk: Any) -> None:
        if mode == "messages":
            message, meta = chunk
            if isinstance(message, AIMessageChunk):
                text = content_text(message.content)
                label = _label(ns, meta.get("langgraph_node"))
                if text and label:
                    self._tokens.setdefault(label, []).append(text)
                    pending = sum(len(t) for t in self._tokens[label])
                    if pending >= self.TOKEN_FLUSH_CHARS or time.monotonic() - self._last_flush > self.TOKEN_FLUSH_SECONDS:
                        await self.flush_tokens()
            return
        if mode == "tasks":
            name = chunk.get("name")
            # An analyst's subgraph declares an output schema, so its "updates" carry only
            # the report; its tool calls and results come from the finished tasks' writes.
            if name in INNER_NODES and isinstance(chunk.get("result"), dict):
                await self._update(ns, name, chunk["result"])
                return
            if name in PIPELINE_NODES:
                if "result" in chunk or "error" in chunk:
                    await self.flush_tokens(only=name)
                    await self.emit(E.node, {"node": name, "phase": "end", "error": str(chunk.get("error") or "") or None})
                else:
                    await self.emit(E.node, {"node": name, "phase": "start"})
            return
        if mode == "custom":
            if isinstance(chunk, dict) and chunk.get("type") in {"risk_check", "approval", "execution"}:
                data = {k: v for k, v in chunk.items() if k != "type"}
                await self.emit(E(chunk["type"]), data)
                self.milestones[chunk["type"]] = data
            return
        if mode == "updates":
            for node, update in (chunk or {}).items():
                await self._update(ns, node, update)

    async def _update(self, ns: tuple[str, ...], node: str, update: Any) -> None:
        if node == "__interrupt__":
            for intr in update or ():
                value = getattr(intr, "value", intr)
                await self.emit(E.approval_required, value if isinstance(value, dict) else {"value": value})
            return
        if not isinstance(update, dict):
            return
        label = _label(ns, node)
        if node in INNER_NODES and label:
            for msg in update.get("messages") or []:
                if isinstance(msg, AIMessage):
                    for call in msg.tool_calls or []:
                        await self.emit(E.tool_call, {"node": label, "tool": call["name"], "args": call["args"]})
                elif isinstance(msg, ToolMessage):
                    await self.emit(E.tool_result, {"node": label, "tool": msg.name,
                                                    "preview": content_text(msg.content)[:400]})
            return
        for key, title in REPORT_TITLES.items():
            if update.get(key):
                await self.emit(E.report, {"key": key, "title": title, "content": update[key]})
                self.milestones.setdefault("reports", {})[key] = update[key]
        if node in DEBATE_NODES and update.get("investment_debate_state"):
            await self.emit(E.debate, {"stage": "investment", "speaker": node,
                                       "content": update["investment_debate_state"].get("current_response", "")})
        if node in RISK_NODES and update.get("risk_debate_state"):
            await self.emit(E.debate, {"stage": "risk", "speaker": node,
                                       "content": update["risk_debate_state"].get(RISK_NODES[node], "")})
        if update.get("investment_plan"):
            await self.emit(E.plan, {"kind": "investment_plan", "content": update["investment_plan"]})
        if update.get("trader_investment_plan"):
            await self.emit(E.plan, {"kind": "trader_plan", "content": update["trader_investment_plan"]})
        if node == "Portfolio Manager" and update.get("final_trade_decision"):
            rating = run_rating(update)
            await self.emit(E.decision, {"rating": rating, "content": update["final_trade_decision"]})
            self.milestones["decision"] = {"rating": rating, "content": update["final_trade_decision"]}
        if node == "Memory Log":
            past = update.get("past_context") or ""
            await self.emit(E.memory, {"lessons": past.count("\n- ") + past.count("\n["),
                                       "note": update.get("memory_note") or ""})


# --- Persistence ---------------------------------------------------------------------

async def _set_status(run_id: str, status: RunStatus, **fields: Any) -> None:
    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return
        run.status = status.value
        for k, v in fields.items():
            setattr(run, k, v)


async def _persist_final(run_id: str, values: dict[str, Any], interrupted: bool, bus: EventBus) -> RunStatus:
    approval = values.get("approval")
    if interrupted:
        status = RunStatus.awaiting_approval
    elif approval and not approval.get("accepted") and approval.get("action") == "reject":
        status = RunStatus.rejected
    else:
        status = RunStatus.completed
    debate = values.get("investment_debate_state") or {}
    risk = values.get("risk_debate_state") or {}
    fields = {
        "reports": {k: values.get(k) or "" for k in REPORT_TITLES if values.get(k)},
        "investment_debate": debate.get("history") or None,
        "risk_debate": risk.get("history") or None,
        "investment_plan": values.get("investment_plan") or None,
        "trader_plan": values.get("trader_investment_plan") or None,
        "final_decision": values.get("final_trade_decision") or None,
        "rating": run_rating(values) if values.get("final_trade_decision") else None,
        "risk_check": values.get("risk_check"),
        "approval": approval,
        "execution": values.get("execution"),
    }
    if status != RunStatus.awaiting_approval:
        fields["finished_at"] = datetime.now(UTC)
    await _set_status(run_id, status, **fields)
    await bus.publish(run_id, E.status, {"status": status.value})
    if status != RunStatus.awaiting_approval:
        await bus.publish(run_id, E.done, {"status": status.value})
    return status


# --- Driving ---------------------------------------------------------------------------

def _graph_for(core: CouncilCore):
    rt = get_runtime()
    graph = getattr(core, "_quantcouncil_graph", None)
    if graph is None:
        graph = build_graph(core, checkpointer=rt.checkpointer, store=rt.store)
        core._quantcouncil_graph = graph  # type: ignore[attr-defined]
    return graph


def _config(run: Run) -> dict[str, Any]:
    trace_id = run.trace_id
    cfg = tracing.run_config(trace_id=trace_id, name=f"analysis {run.ticker} {run.trade_date}", session_id=run.id,
                             tags=[run.ticker, run.market, run.source],
                             metadata={"run_id": run.id, "trade_date": str(run.trade_date)})
    return {"configurable": {"thread_id": run.id}, "recursion_limit": 300, **cfg}


async def _drive(run: Run, core: CouncilCore, graph_input: Any) -> RunStatus:
    rt = get_runtime()
    graph = _graph_for(core)
    config = _config(run)
    mapper = EventMapper(run.id, rt.bus)
    try:
        with run_config(core.config):
            async for ns, mode, chunk in graph.astream(graph_input, config, subgraphs=True,
                                                       stream_mode=["tasks", "updates", "messages", "custom"]):
                await mapper.handle(ns, mode, chunk)
        await mapper.flush_tokens()
        snapshot = await graph.aget_state(config)
        interrupted = bool(snapshot.next) and any(t.interrupts for t in snapshot.tasks)
        return await _persist_final(run.id, snapshot.values, interrupted, rt.bus)
    except Exception as exc:
        logger.exception("run %s failed", run.id)
        await mapper.flush_tokens()
        await _set_status(run.id, RunStatus.failed, error=f"{type(exc).__name__}: {exc}",
                          finished_at=datetime.now(UTC))
        await rt.bus.publish(run.id, E.error, {"message": f"{type(exc).__name__}: {exc}"})
        await rt.bus.publish(run.id, E.status, {"status": RunStatus.failed.value})
        await rt.bus.publish(run.id, E.done, {"status": RunStatus.failed.value})
        return RunStatus.failed
    finally:
        await asyncio.to_thread(tracing.flush)


async def _core_for(run: Run) -> CouncilCore:
    """The core for a run, built from the LLM settings pinned when the run started."""
    async with session_scope() as session:
        settings, overrides = await llm_settings.resolve(session, (run.options or {}).get("llm"))
    if (run.options or {}).get("max_debate_rounds"):
        overrides["max_debate_rounds"] = run.options["max_debate_rounds"]
    return get_core(Instrument(run.ticker, run.market), run.analysts, store=get_runtime().store,
                    overrides=overrides)


async def _portfolio_context(run: Run) -> PortfolioContext | None:
    """The paper account as the decision agents see it: cash and holdings on the trade date."""
    if run.market != "CN":
        return None  # The paper account is CNY-only; US research has no USD book yet.
    async with session_scope() as session:
        book = await ledger.book_view(session, run.account_id, run.trade_date, get_settings().initial_cash)
    return PortfolioContext(cash=round(book.cash, 2), currency="CNY", positions=[
        Position(ticker=t, quantity=h.quantity, average_price=round(h.avg_cost, 2)) for t, h in book.positions.items()])


async def start_run(run_id: str) -> str:
    rt = get_runtime()
    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None or run.status != RunStatus.queued.value:
            logger.info("run %s not startable (%s)", run_id, run.status if run else "missing")
            return run.status if run else "missing"
        run.status = RunStatus.running.value
        run.started_at = datetime.now(UTC)
        run.trace_id = run.trace_id or tracing.trace_id_for(run.id)
        settings, _ = await llm_settings.resolve(session)
        run.options = {**(run.options or {}), "llm": settings.model_dump()}
        if run.trace_id:
            run.options = {**(run.options or {}), "trace_url": tracing.trace_url(run.trace_id)}
    await rt.bus.publish(run_id, E.status, {"status": RunStatus.running.value})

    core = await _core_for(run)
    portfolio = await _portfolio_context(run)

    def initial_state() -> dict:
        with run_config(core.config):
            return core.create_run_state(run.ticker, str(run.trade_date), portfolio=portfolio)

    try:
        init = await asyncio.to_thread(initial_state)
    except Exception as exc:  # noqa: BLE001
        await _set_status(run_id, RunStatus.failed, error=f"could not build the run state: {exc}",
                          finished_at=datetime.now(UTC))
        await rt.bus.publish(run_id, E.error, {"message": str(exc)})
        await rt.bus.publish(run_id, E.done, {"status": RunStatus.failed.value})
        return RunStatus.failed.value
    init.update(run_id=run.id, market=run.market, account_id=run.account_id, auto_approve=run.auto_approve,
                risk_check=None, approval=None, execution=None)
    status = await _drive(run, core, init)
    return status.value


async def resume_run(run_id: str, decision: dict[str, Any]) -> str:
    rt = get_runtime()
    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None or run.status != RunStatus.awaiting_approval.value:
            return run.status if run else "missing"
        run.status = RunStatus.running.value
    await rt.bus.publish(run_id, E.status, {"status": RunStatus.running.value})
    status = await _drive(run, await _core_for(run), Command(resume=decision))
    return status.value


async def retry_run(run_id: str) -> str:
    """Re-drive a failed run from its last checkpoint: finished nodes are not re-run
    (LangGraph durable execution; input ``None`` resumes the thread)."""
    rt = get_runtime()
    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None or run.status != RunStatus.failed.value:
            return run.status if run else "missing"
        run.status = RunStatus.running.value
        run.error = None
        run.finished_at = None
    await rt.bus.publish(run_id, E.status, {"status": RunStatus.running.value})
    core = await _core_for(run)
    snapshot = await _graph_for(core).aget_state(_config(run))
    if not snapshot.next:  # failed before the first checkpoint: start over
        async with session_scope() as session:
            (await session.get(Run, run_id)).status = RunStatus.queued.value
        return await start_run(run_id)
    status = await _drive(run, core, None)
    return status.value
