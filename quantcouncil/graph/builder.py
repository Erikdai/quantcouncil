"""The QuantCouncil graph: the TradingAgents analysis graph as a subgraph, then execution.

    analysis ─► Risk Gate ─┬─► Human Approval (interrupt) ─┬─► Execute ─► Record
                           ├─► Execute (auto-approve)      └─► Record (rejected)
                           └─► Record (no order)

Compiled with the Postgres checkpointer (thread id = run id), so a run paused for
approval survives restarts and resumes on any worker.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from quantcouncil.graph import nodes
from quantcouncil.graph.core import CouncilCore
from quantcouncil.graph.state import CouncilState

ANALYSIS = "analysis"


def build_graph(core: CouncilCore, *, checkpointer=None, store=None):
    g = StateGraph(CouncilState)
    g.add_node(ANALYSIS, core.workflow.compile())
    g.add_node(nodes.RISK_GATE, nodes.risk_gate)
    g.add_node(nodes.HUMAN_APPROVAL, nodes.human_approval)
    g.add_node(nodes.EXECUTE, nodes.execute)
    g.add_node(nodes.RECORD, nodes.make_record(core))

    g.add_edge(START, ANALYSIS)
    g.add_edge(ANALYSIS, nodes.RISK_GATE)
    g.add_conditional_edges(nodes.RISK_GATE, nodes.after_risk_gate,
                            [nodes.HUMAN_APPROVAL, nodes.EXECUTE, nodes.RECORD])
    g.add_conditional_edges(nodes.HUMAN_APPROVAL, nodes.after_approval,
                            [nodes.HUMAN_APPROVAL, nodes.EXECUTE, nodes.RECORD])
    g.add_edge(nodes.EXECUTE, nodes.RECORD)
    g.add_edge(nodes.RECORD, END)
    return g.compile(checkpointer=checkpointer, store=store, name="quantcouncil")
