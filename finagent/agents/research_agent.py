"""Research assistant: a ReAct StateGraph over RAG, MCP tools and skills, checkpointed per conversation."""

from __future__ import annotations

import logging
import operator
import uuid
from collections.abc import AsyncIterator
from datetime import date
from typing import Annotated, Any

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from finagent import llm_settings
from finagent.api.schemas import ChatMessage
from finagent.db import session_scope
from finagent.markets import CN_DEFAULT, agent_config
from finagent.messages import content_text
from finagent.observability import tracing
from finagent.rag.retriever import format_hits, search, to_citation
from finagent.runtime import get_runtime
from finagent.skills import load_skill, skills_index_prompt
from tradingagents.llm_clients import create_tier_client

logger = logging.getLogger(__name__)

MCP_TOOLS = ("get_market_snapshot", "get_company_fundamentals", "get_financial_statement", "get_research_reports",
             "get_company_news", "get_dragon_tiger", "get_market_breadth", "get_china_macro")


class ChatState(MessagesState):
    citations: Annotated[list[dict], operator.add]


@tool(response_format="content_and_artifact")
async def search_research_docs(query: str, ticker: str | None = None) -> tuple[str, list[dict]]:
    """Search ingested exchange announcements and broker research reports (hybrid vector + keyword
    search with reranking). Returns numbered passages; cite them as [n] in the answer.
    ticker: optional A-share code to restrict the search, e.g. 600519."""
    from finagent.markets import resolve_instrument  # noqa: PLC0415

    t = resolve_instrument(ticker).ticker if ticker else None
    hits = await search(query, ticker=t, k=6)
    return format_hits(hits), [to_citation(h).model_dump(mode="json") for h in hits]


SYSTEM = """You are FinAgent's A-share research assistant (A股投研助手). Today is {today}.
Answer in the user's language (default Simplified Chinese), concisely, with numbers and dates.

Rules:
- Ground every factual claim in a tool result. For company documents use search_research_docs and cite
  passages as [n]; for prices, valuation, financials and money flow use the market tools with as_of_date={today}.
- If the tools do not have it, say so. Never invent figures, and do not give personalised investment advice;
  frame conclusions as research views with their risks.
{scope}
{skills}"""


async def _tools() -> list:
    tools = [search_research_docs, load_skill]
    try:
        from finagent.mcp_client import load_tools  # noqa: PLC0415

        tools += await load_tools(list(MCP_TOOLS))
    except Exception as exc:  # noqa: BLE001 — chat still works on the corpus alone
        logger.warning("research agent without MCP tools: %s", exc)
    return tools


_graph = None
_graph_fingerprint: str | None = None


async def get_graph():
    """The compiled assistant for the current LLM settings (rebuilt when they change)."""
    global _graph, _graph_fingerprint
    async with session_scope() as session:
        settings, overrides = await llm_settings.resolve(session)
    fingerprint = llm_settings.fingerprint(settings, overrides.get("api_key"))
    if _graph is None or fingerprint != _graph_fingerprint:
        _graph_fingerprint = fingerprint
        tools = await _tools()
        llm = create_tier_client(agent_config(CN_DEFAULT, overrides=overrides), "quick").get_llm()
        model = llm.bind_tools(tools)

        async def agent(state: ChatState) -> dict:
            return {"messages": [await model.ainvoke(state["messages"])]}

        async def collect(state: ChatState) -> dict:
            """Pull citations out of the last tool results (artifacts) into state."""
            cites = []
            for msg in reversed(state["messages"]):
                if not isinstance(msg, ToolMessage):
                    break
                if msg.name == "search_research_docs" and isinstance(msg.artifact, list):
                    cites.extend(msg.artifact)
            return {"citations": cites}

        g = StateGraph(ChatState)
        g.add_node("agent", agent)
        g.add_node("tools", ToolNode(tools))
        g.add_node("collect", collect)
        g.add_edge(START, "agent")
        g.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
        g.add_edge("tools", "collect")
        g.add_edge("collect", "agent")
        rt = get_runtime()
        _graph = g.compile(checkpointer=rt.checkpointer, name="research_assistant")
    return _graph


async def stream_chat(messages: list[ChatMessage], *, ticker: str | None = None,
                      thread_id: str | None = None) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yield (event, data) pairs: token, tool_call, tool_result, citations, done | error."""
    try:
        graph = await get_graph()
        today = date.today().isoformat()
        scope = f"The user is asking about {ticker}; prefer it as the ticker argument." if ticker else ""
        system = SystemMessage(SYSTEM.format(today=today, scope=scope, skills=skills_index_prompt()))
        thread = thread_id or str(uuid.uuid4())
        config: dict[str, Any] = {"configurable": {"thread_id": f"chat:{thread}"}, "recursion_limit": 30}
        trace = tracing.trace_id_for(f"chat:{thread}:{len(messages)}")
        config.update(tracing.run_config(trace_id=trace, name="research chat", session_id=f"chat:{thread}",
                                         tags=["chat"] + ([ticker] if ticker else [])))
        existing = await graph.aget_state(config)
        if thread_id and existing.values.get("messages"):
            new_messages = [HumanMessage(messages[-1].content)]  # the thread holds the history and system
        else:
            new_messages = [system] + [HumanMessage(m.content) if m.role == "user" else AIMessage(m.content)
                                       for m in messages]
        seen_citations = 0
        async for mode, chunk in graph.astream({"messages": new_messages, "citations": []}, config,
                                               stream_mode=["messages", "updates"]):
            if mode == "messages":
                msg, meta = chunk
                if isinstance(msg, AIMessageChunk) and meta.get("langgraph_node") == "agent":
                    text = content_text(msg.content)
                    if text:
                        yield "token", {"text": text}
            elif mode == "updates":
                for node, update in chunk.items():
                    if node == "agent":
                        for call in update["messages"][-1].tool_calls or []:
                            yield "tool_call", {"tool": call["name"], "args": call["args"]}
                    elif node == "tools":
                        for m in update.get("messages", []):
                            yield "tool_result", {"tool": m.name, "preview": content_text(m.content)[:300]}
                    elif node == "collect" and update.get("citations"):
                        items = update["citations"]
                        seen_citations += len(items)
                        yield "citations", {"items": items}
        yield "done", {"thread_id": thread, "citations": seen_citations, "trace_url": tracing.trace_url(trace)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("chat failed")
        yield "error", {"message": f"{type(exc).__name__}: {exc}"}
