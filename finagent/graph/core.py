"""TradingAgents' graph configured for a market, with an async memory step adding semantic recall."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from langgraph.store.base import BaseStore

from finagent.markets import Instrument, agent_config, core_analysts
from finagent.memory import store as semantic
from tradingagents.graph.trading_graph import TradingAgentsGraph

logger = logging.getLogger(__name__)


class FinAgentCore(TradingAgentsGraph):
    store: BaseStore | None = None

    async def _memory_step(self, state):  # type: ignore[override]
        base = await asyncio.to_thread(super()._memory_step, state)
        if self.store is None:
            return base
        situation = f"{state['company_of_interest']} {state.get('instrument_context', '')[:300]}"
        lessons = await semantic.recall(self.store, query=situation, ticker=state["company_of_interest"],
                                        as_of=state["trade_date"])
        if lessons:
            block = "\n".join(f"- {line}" for line in lessons)
            past = (base.get("past_context") or "").strip()
            base["past_context"] = (past + "\n\n" if past else "") + (
                "Lessons from similar past situations (semantic memory, other tickers included):\n" + block)
        # The core's state has no slot for them; the Portfolio Manager reads past_context.
        return base


_cores: dict[tuple, FinAgentCore] = {}
_lock = threading.Lock()


def get_core(instrument: Instrument, analysts: list[str] | None, *, store: BaseStore | None = None,
             overrides: dict[str, Any] | None = None) -> FinAgentCore:
    """A core per (market, analysts, LLM settings), built once per process."""
    keys = core_analysts(instrument.market, analysts)
    cfg_overrides = dict(overrides or {})
    key = (instrument.market, tuple(keys), tuple(sorted((k, str(v)) for k, v in cfg_overrides.items())))
    with _lock:
        core = _cores.get(key)
        if core is None:
            config = agent_config(instrument, overrides=cfg_overrides)
            core = FinAgentCore(selected_analysts=keys, config=config)
            _cores[key] = core
        if store is not None:
            core.store = store
    return core


def clear_cores() -> None:
    with _lock:
        _cores.clear()
