"""HTTP contract of the API.

Run lifecycle: queued -> running -> (awaiting_approval -> running) -> completed | rejected | failed.
Live progress streams from ``GET /api/runs/{id}/events`` as SSE messages carrying a
Redis Stream id, an event type (``RunEventType``) and a ``RunEvent`` payload.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class RunStatus(StrEnum):
    queued = "queued"
    running = "running"
    awaiting_approval = "awaiting_approval"
    completed = "completed"
    rejected = "rejected"
    failed = "failed"


TERMINAL_STATUSES = {RunStatus.completed, RunStatus.rejected, RunStatus.failed}


class RunEventType(StrEnum):
    status = "status"                    # {status}
    node = "node"                        # {node, phase: "start"|"end"} an agent began / finished
    token = "token"                      # {node, text} streamed LLM text delta
    tool_call = "tool_call"              # {node, tool, args}
    tool_result = "tool_result"          # {node, tool, preview}
    report = "report"                    # {key, title, content} an analyst report was filed
    debate = "debate"                    # {stage: "investment"|"risk", speaker, content}
    plan = "plan"                        # {kind: "investment_plan"|"trader_plan", content}
    decision = "decision"                # {rating, content} Portfolio Manager's decision
    risk_check = "risk_check"            # RiskCheck
    approval_required = "approval_required"  # {order, risk_check}
    approval = "approval"                # {action, quantity, comment}
    execution = "execution"              # Execution
    memory = "memory"                    # {lessons: int, note}
    done = "done"                        # {status}
    error = "error"                      # {message}


class RunEvent(BaseModel):
    type: RunEventType
    run_id: str
    ts: datetime
    data: dict[str, Any] = Field(default_factory=dict)


class RunCreate(BaseModel):
    ticker: str = Field(description="A-share code in any form (600519, 600519.SH, sz000001) or a US ticker")
    trade_date: date | None = Field(default=None, description="Analysis date; defaults to the latest trading day")
    analysts: list[str] | None = Field(
        default=None, description="Subset of market, sentiment, news, fundamentals; default all for the market")
    auto_approve: bool = Field(default=False, description="Skip the human approval step (scheduled runs)")
    account_id: str = "default"
    max_debate_rounds: int | None = Field(default=None, ge=1, le=5)


class RiskViolation(BaseModel):
    rule: str
    message: str
    severity: Literal["block", "warn"] = "block"


class OrderProposal(BaseModel):
    ticker: str
    side: Literal["buy", "sell"]
    quantity: int = Field(description="Shares, a multiple of the 100-share lot for buys")
    price: float = Field(description="Reference fill price (CNY)")
    notional: float
    est_fees: float
    target_weight: float
    current_weight: float


class RiskCheck(BaseModel):
    rating: str
    approved: bool = Field(description="True when an order exists and no blocking rule fired")
    order: OrderProposal | None = None
    violations: list[RiskViolation] = Field(default_factory=list)
    warnings: list[RiskViolation] = Field(default_factory=list)
    reference: dict[str, Any] = Field(default_factory=dict, description="Prices and limits the check used")


class ApprovalRequest(BaseModel):
    action: Literal["approve", "reject", "modify"]
    quantity: int | None = Field(default=None, description="New quantity when action is modify")
    comment: str | None = None


class Execution(BaseModel):
    order_id: str
    ticker: str
    side: Literal["buy", "sell"]
    quantity: int
    price: float
    fees: dict[str, float]
    cash_after: float
    status: Literal["filled", "rejected"]
    reason: str | None = None


class RunSummary(BaseModel):
    id: str
    ticker: str
    name: str | None = None
    market: str
    trade_date: date
    status: RunStatus
    rating: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class RunOut(RunSummary):
    analysts: list[str]
    auto_approve: bool
    reports: dict[str, str] = Field(default_factory=dict, description="market_report, sentiment_report, ...")
    investment_debate: str | None = None
    risk_debate: str | None = None
    investment_plan: str | None = None
    trader_plan: str | None = None
    final_decision: str | None = None
    risk_check: RiskCheck | None = None
    approval: dict[str, Any] | None = None
    execution: Execution | None = None
    error: str | None = None
    trace_url: str | None = None
    llm: dict[str, Any] | None = Field(default=None, description="Provider and models the run used (no keys)")
    evals: list[EvalResultOut] = Field(default_factory=list)


class AccountOut(BaseModel):
    id: str
    cash: float
    initial_cash: float
    market_value: float
    equity: float
    pnl: float
    pnl_pct: float
    peak_equity: float
    drawdown_pct: float


class PositionOut(BaseModel):
    ticker: str
    name: str | None = None
    quantity: int
    available_quantity: int = Field(description="Sellable today (T+1: shares bought today are not)")
    avg_cost: float
    last_price: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None
    weight: float | None = None


class PortfolioOut(BaseModel):
    account: AccountOut
    positions: list[PositionOut]
    ledger_verified: bool = Field(description="Hash chain of the ledger re-verified on read")


class OrderOut(BaseModel):
    id: str
    run_id: str | None
    ticker: str
    side: str
    quantity: int
    price: float
    fees: float
    status: str
    comment: str | None = None
    created_at: datetime


class Bar(BaseModel):
    time: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: float


class KlineOut(BaseModel):
    ticker: str
    name: str | None = None
    bars: list[Bar]


class WatchItem(BaseModel):
    ticker: str
    name: str | None = None
    enabled: bool = True
    added_at: datetime | None = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    ticker: str | None = None
    thread_id: str | None = None


class Citation(BaseModel):
    chunk_id: int
    document_id: int
    title: str
    url: str | None = None
    ticker: str | None = None
    published_at: date | None = None
    doc_type: str
    snippet: str
    score: float


class SearchOut(BaseModel):
    query: str
    mode: str
    results: list[Citation]


class IngestRequest(BaseModel):
    ticker: str
    kinds: list[Literal["announcement", "research"]] = Field(default_factory=lambda: ["announcement", "research"])
    since: date | None = None
    limit: int = Field(default=10, ge=1, le=50)


class DocumentOut(BaseModel):
    id: int
    ticker: str | None
    title: str
    doc_type: str
    url: str | None
    published_at: date | None
    chunks: int
    created_at: datetime


class SkillOut(BaseModel):
    name: str
    description: str
    body: str | None = None


class EvalResultOut(BaseModel):
    id: int
    run_id: str
    evaluator: str
    scores: dict[str, float]
    passed: bool
    comment: str | None = None
    created_at: datetime


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    services: dict[str, str]


RunOut.model_rebuild()
