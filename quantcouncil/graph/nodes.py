"""Post-analysis nodes: risk gate, human approval (interrupt), paper execution, record. No LLM calls."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import date

from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from quantcouncil.api.schemas import OrderProposal, RiskCheck, RiskViolation
from quantcouncil.config import get_fee_schedule, get_risk_limits, get_settings
from quantcouncil.db import session_scope
from quantcouncil.graph.state import CouncilState
from quantcouncil.portfolio import ledger
from quantcouncil.risk import evaluate, market_ref_for
from tradingagents.agents.rating import run_rating

logger = logging.getLogger(__name__)

RISK_GATE, HUMAN_APPROVAL, EXECUTE, RECORD = "Risk Gate", "Human Approval", "Execute", "Record"


def _emit(event: dict) -> None:
    """Custom stream event for the run's SSE feed (no-op outside a streamed run)."""
    with contextlib.suppress(Exception):
        get_stream_writer()(event)


async def _check(state: CouncilState, quantity: int | None = None, side: str | None = None) -> RiskCheck:
    rating = run_rating(state)
    ticker, trade_date = state["company_of_interest"], state["trade_date"]
    settings = get_settings()
    ref = await asyncio.to_thread(market_ref_for, ticker, trade_date)
    async with session_scope() as session:
        book = await ledger.book_view(session, state.get("account_id") or settings.default_account,
                                      date.fromisoformat(trade_date), settings.initial_cash,
                                      price_of=lambda t: ref.close if t == ticker else None)
    return evaluate(rating, ref, book, get_risk_limits(), get_fee_schedule(), quantity_override=quantity, side=side)


async def risk_gate(state: CouncilState) -> dict:
    rating = run_rating(state)
    if state.get("market") != "CN":
        check = RiskCheck(rating=rating, approved=False, warnings=[RiskViolation(
            rule="market_not_supported", severity="warn",
            message="Paper trading covers A-shares only; this run stops at the decision.")])
    else:
        try:
            check = await _check(state)
        except Exception as exc:  # noqa: BLE001 — no price, no order
            logger.warning("risk gate could not price %s: %s", state["company_of_interest"], exc)
            check = RiskCheck(rating=rating, approved=False, violations=[RiskViolation(
                rule="no_reference_price", message=f"No reference price for the trade date ({exc}).")])
    out = check.model_dump(mode="json")
    _emit({"type": "risk_check", **out})
    return {"risk_check": out, "approval": None, "execution": None}


def after_risk_gate(state: CouncilState) -> str:
    check = state.get("risk_check") or {}
    if not check.get("approved"):
        return RECORD
    return EXECUTE if state.get("auto_approve") else HUMAN_APPROVAL


async def human_approval(state: CouncilState) -> dict:
    """Pause the run until a person approves, rejects or resizes the order.

    The interrupt payload is what the UI shows; ``Command(resume=...)`` carries
    ``{"action": "approve"|"reject"|"modify", "quantity": int, "comment": str}``.
    A resized order is re-checked by the same rules; if it fails, the person is
    asked again with the violations shown.
    """
    check = state["risk_check"]
    previous = state.get("approval")  # feedback when a resize was refused
    decision = interrupt({"type": "order_approval", "order": check.get("order"), "risk_check": check,
                          "feedback": previous if previous and not previous.get("accepted") else None})
    action = (decision or {}).get("action", "reject")
    comment = (decision or {}).get("comment")
    if action == "modify":
        requested = int(decision.get("quantity") or 0)
        new = await _check(state, quantity=requested, side=check["order"]["side"])
        if new.approved:
            approval = {"action": "modify", "quantity": new.order.quantity, "comment": comment, "accepted": True}
            _emit({"type": "approval", **approval})
            return {"risk_check": new.model_dump(mode="json"), "approval": approval}
        # The original proposal stands; ask again, showing why the resize failed.
        approval = {"action": "modify", "quantity": requested, "comment": comment, "accepted": False,
                    "violations": [v.model_dump() for v in new.violations]}
        _emit({"type": "approval", **approval})
        return {"approval": approval}
    approval = {"action": action, "quantity": (check.get("order") or {}).get("quantity"), "comment": comment,
                "accepted": action == "approve"}
    _emit({"type": "approval", **approval})
    return {"approval": approval}


def after_approval(state: CouncilState) -> str:
    approval = state.get("approval") or {}
    if approval.get("action") == "modify" and not approval.get("accepted"):
        return HUMAN_APPROVAL
    return EXECUTE if approval.get("accepted") else RECORD


async def execute(state: CouncilState) -> dict:
    settings = get_settings()
    order = OrderProposal.model_validate(state["risk_check"]["order"])
    approval = state.get("approval") or {}
    async with session_scope() as session:
        result = await ledger.execute(
            session, state.get("account_id") or settings.default_account, order,
            date.fromisoformat(state["trade_date"]), state.get("run_id"), settings.initial_cash,
            comment=approval.get("comment") or ("auto-approved" if state.get("auto_approve") else None),
            name=state["risk_check"].get("reference", {}).get("name"))
    out = result.model_dump(mode="json")
    _emit({"type": "execution", **out})
    return {"execution": out}


def make_record(core):
    """Record the decision: the core's state log and markdown memory log, and the semantic store."""

    async def record(state: CouncilState, config: RunnableConfig) -> dict:
        from quantcouncil.memory import store as semantic  # noqa: PLC0415

        ticker, trade_date = state["company_of_interest"], state["trade_date"]
        try:
            await asyncio.to_thread(core.record_decision, ticker, trade_date, state)
        except Exception as exc:  # noqa: BLE001 — bookkeeping must not fail a finished run
            logger.warning("record_decision failed: %s", exc)
        if core.store is not None and state.get("final_trade_decision"):
            try:
                await semantic.remember_decision(
                    core.store, run_id=state.get("run_id") or "", ticker=ticker, trade_date=trade_date,
                    rating=run_rating(state), decision=state["final_trade_decision"],
                    situation=state.get("instrument_context", ""))
            except Exception as exc:  # noqa: BLE001
                logger.warning("semantic memory write failed: %s", exc)
        return {}

    return record
