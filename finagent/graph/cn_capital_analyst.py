"""A-share capital and sentiment analyst. Takes the core's sentiment seat with MCP tools
(Dragon-Tiger list, margin, market breadth, sell-side research) and writes ``sentiment_report``.
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from finagent.skills import get_skill
from tradingagents.agents.analysts.turn import take_turn
from tradingagents.agents.context import get_instrument_context_from_state, get_language_instruction
from tradingagents.graph.analyst_execution import AnalystNodeSpec, register_analyst

KEY = "cn_capital"
NODE = "Sentiment Analyst"
TOOL_NAMES = (
    "get_dragon_tiger", "get_margin_trading", "get_market_breadth", "get_research_reports",
    "get_fund_flow", "get_company_news", "get_market_telegraph",
)

SYSTEM = """You are the A-share capital-flow and sentiment analyst on a trading desk. Judge short-term \
capital sentiment toward the stock and the market from the tools, not from opinion.

Work plan:
1. get_market_breadth for the trade date: is speculative appetite hot or cold?
2. get_dragon_tiger (30 days) and get_margin_trading (5 sessions) for the stock: who is buying with what leverage?
3. get_research_reports (90 days): sell-side ratings and the EPS consensus and how it moved.
4. get_fund_flow (may be unavailable outside mainland China) and get_company_news / get_market_telegraph for catalysts.
Call each tool at most twice. Always pass the trade date {current_date} as as_of_date.

{playbook}

Write a detailed report: an overall verdict (偏多 / 中性 / 偏空) with confidence, the evidence with dates and \
numbers, what would change the view, and a Markdown table of the key signals at the end. If a tool returns \
DATA_UNAVAILABLE or NO_DATA, say which data is missing; never invent figures."""


def make_capital_analyst(tools):
    tools = tuple(tools)

    def create(llm):
        def capital_analyst_node(state):
            skill = get_skill("dragon-tiger-reading")
            prompt = ChatPromptTemplate.from_messages([
                ("system",
                 "You are a helpful AI assistant, collaborating with other assistants. Use the provided tools to "
                 "progress towards answering the question. Report what your tools support; another agent decides "
                 "the trade. You have access to the following tools: {tool_names}. Today's date is "
                 "{current_date}; treat it as 'now'. {instrument_context}\n{system_message}"),
                MessagesPlaceholder(variable_name="messages"),
            ]).partial(
                system_message=SYSTEM.format(
                    current_date=state["trade_date"],
                    playbook=f"Playbook (dragon-tiger-reading skill):\n{skill.body}" if skill else "",
                ) + get_language_instruction(),
                tool_names=", ".join(t.name for t in tools),
                current_date=state["trade_date"],
                instrument_context=get_instrument_context_from_state(state),
            )
            result, report = take_turn(prompt, llm, tools, state["messages"])
            return {"messages": [result], "sentiment_report": report}

        return capital_analyst_node

    return create


def register(tools) -> None:
    """Register the analyst under ``cn_capital`` with the given MCP tools."""
    selected = [t for t in tools if t.name in TOOL_NAMES]
    register_analyst(
        AnalystNodeSpec(key=KEY, agent_node=NODE, report_key="sentiment_report", tools=tuple(selected)),
        make_capital_analyst(selected),
    )
