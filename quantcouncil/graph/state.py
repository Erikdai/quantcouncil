"""State of the QuantCouncil graph: the core's AgentState plus the execution pipeline."""

from __future__ import annotations

from typing import Annotated, Any

from tradingagents.agents.state import AgentState


class CouncilState(AgentState):
    """Parent-graph state. The analysis subgraph reads and writes the AgentState
    keys; the nodes after it add the order's life cycle."""

    run_id: Annotated[str, "Platform run id (also the checkpoint thread id)"]
    market: Annotated[str, "CN or US"]
    account_id: Annotated[str, "Paper account the order books to"]
    auto_approve: Annotated[bool, "Skip human approval (scheduled runs)"]
    risk_check: Annotated[dict[str, Any] | None, "RiskCheck from the deterministic gate"]
    approval: Annotated[dict[str, Any] | None, "The human's decision on the order"]
    execution: Annotated[dict[str, Any] | None, "Paper fill"]
