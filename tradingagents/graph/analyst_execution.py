from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from tradingagents.agents.analysts import fundamentals_analyst, market_analyst, news_analyst


@dataclass(frozen=True)
class AnalystNodeSpec:
    key: str
    agent_node: str
    report_key: str
    tools: tuple = ()


@dataclass(frozen=True)
class AnalystExecutionPlan:
    specs: list[AnalystNodeSpec]


ANALYST_NODE_SPECS: dict[str, AnalystNodeSpec] = {
    "market": AnalystNodeSpec(
        key="market",
        agent_node="Market Analyst",
        report_key="market_report",
        tools=market_analyst.TOOLS,
    ),
    "social": AnalystNodeSpec(
        # Saved configs select this analyst as "social". It fetches its
        # sources before calling the model, so it has no tools.
        key="social",
        agent_node="Sentiment Analyst",
        report_key="sentiment_report",
    ),
    "news": AnalystNodeSpec(
        key="news",
        agent_node="News Analyst",
        report_key="news_report",
        tools=news_analyst.TOOLS,
    ),
    "fundamentals": AnalystNodeSpec(
        key="fundamentals",
        agent_node="Fundamentals Analyst",
        report_key="fundamentals_report",
        tools=fundamentals_analyst.TOOLS,
    ),
}


# Analysts registered from outside the core (e.g. a market-specific analyst whose
# tools come from an MCP server): key -> factory taking the quick-think LLM.
EXTRA_ANALYST_FACTORIES: dict[str, Callable[[Any], Callable]] = {}


def register_analyst(spec: AnalystNodeSpec, factory: Callable[[Any], Callable]) -> None:
    """Add an analyst the graph can select by ``spec.key``.

    ``spec.report_key`` must be a key of ``AgentState`` that the downstream
    agents read (e.g. ``sentiment_report``), so the new analyst slots into the
    debate without changing it.
    """
    ANALYST_NODE_SPECS[spec.key] = spec
    EXTRA_ANALYST_FACTORIES[spec.key] = factory


def build_analyst_execution_plan(
    selected_analysts: Iterable[str],
) -> AnalystExecutionPlan:
    specs: list[AnalystNodeSpec] = []
    for analyst_key in selected_analysts:
        spec = ANALYST_NODE_SPECS.get(analyst_key)
        if spec is None:
            raise ValueError(f"unknown analyst key: {analyst_key}")
        specs.append(spec)

    if not specs:
        raise ValueError("at least one analyst must be selected")

    return AnalystExecutionPlan(specs=specs)


