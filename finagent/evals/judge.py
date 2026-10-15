"""LLM-as-judge scoring of a run's decision against its reports, plus deterministic checks."""

from __future__ import annotations

import asyncio
import json
import logging
import statistics

from pydantic import BaseModel, Field

from finagent import llm_settings
from finagent.api.schemas import EvalResultOut
from finagent.db import session_scope
from finagent.db.models import EvalResult, Run
from finagent.markets import Instrument, agent_config
from finagent.observability import tracing
from tradingagents.agents.rating import RATINGS_5_TIER
from tradingagents.llm_clients import create_tier_client

logger = logging.getLogger(__name__)
PASS_MEAN = 3.5

RUBRIC = """Score each criterion from 1 (poor) to 5 (excellent):

- grounding: every number and factual claim in the decision is traceable to the analyst reports; 1 = invents
  figures or contradicts the reports, 5 = all claims supported.
- consistency: the rating follows from the thesis and the evidence weighed; 1 = rating contradicts the argument,
  5 = tightly argued.
- balance: bull and bear evidence are both weighed and the strongest counter-argument is answered.
- risk_awareness: names the key downside risks, the invalidation level or event, and market constraints
  (A-share price limits, T+1, liquidity) where relevant.
- actionability: states position sizing / entry / exit guidance a trader could act on.

Be strict: a confident decision built on missing data scores low on grounding."""


class JudgeScores(BaseModel):
    grounding: int = Field(ge=1, le=5)
    consistency: int = Field(ge=1, le=5)
    balance: int = Field(ge=1, le=5)
    risk_awareness: int = Field(ge=1, le=5)
    actionability: int = Field(ge=1, le=5)
    critique: str = Field(description="Two or three sentences: the main weakness and what would fix it")


def deterministic_checks(run: Run) -> dict[str, float]:
    reports = run.reports or {}
    expected = len(run.analysts or [])
    return {
        "rating_valid": float(run.rating in RATINGS_5_TIER),
        "reports_complete": round(sum(1 for v in reports.values() if v and len(v) > 200) / max(expected, 1), 2),
        "decision_present": float(bool(run.final_decision and len(run.final_decision) > 300)),
        "risk_gate_ran": float(run.risk_check is not None),
    }


def _judge_prompt(run: Run) -> str:
    reports = "\n\n".join(f"### {k}\n{(v or '')[:4000]}" for k, v in (run.reports or {}).items())
    return (f"You are auditing an equity research desk's output for {run.ticker} on {run.trade_date}.\n\n{RUBRIC}\n\n"
            f"## Analyst reports (evidence)\n{reports}\n\n## Research manager plan\n{(run.investment_plan or '')[:3000]}"
            f"\n\n## Final decision (to score)\n{(run.final_decision or '')[:6000]}")


def judge(run: Run, overrides: dict | None = None) -> JudgeScores:
    cfg = agent_config(Instrument(run.ticker, run.market), overrides=overrides)
    llm = create_tier_client(cfg, "deep").get_llm()
    prompt = _judge_prompt(run)
    try:
        return llm.with_structured_output(JudgeScores).invoke(prompt)
    except Exception as exc:  # noqa: BLE001 — providers without tool calling: ask for JSON
        logger.info("structured judge failed (%s); falling back to JSON", exc)
        raw = llm.invoke(prompt + "\n\nAnswer with only a JSON object with keys grounding, consistency, balance, "
                                  "risk_awareness, actionability (integers 1-5) and critique (string).").content
        start, end = raw.find("{"), raw.rfind("}")
        return JudgeScores.model_validate(json.loads(raw[start:end + 1]))


async def evaluate_and_store(run_id: str) -> EvalResultOut:
    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise ValueError(f"run {run_id} not found")
        checks = deterministic_checks(run)
        _, overrides = await llm_settings.resolve(session)
        scores = await asyncio.to_thread(judge, run, overrides)
        judged = {k: float(getattr(scores, k)) for k in ("grounding", "consistency", "balance", "risk_awareness",
                                                          "actionability")}
        mean = statistics.mean(judged.values())
        all_scores = {**judged, "judge_mean": round(mean, 2), **checks}
        passed = mean >= PASS_MEAN and checks["rating_valid"] == 1 and checks["decision_present"] == 1
        row = EvalResult(run_id=run_id, evaluator="llm_judge_v1", scores=all_scores, passed=passed,
                         comment=scores.critique)
        session.add(row)
        await session.flush()
        trace_id = run.trace_id
        out = EvalResultOut(id=row.id, run_id=run_id, evaluator=row.evaluator, scores=all_scores, passed=passed,
                            comment=row.comment, created_at=row.created_at)
    for name, value in all_scores.items():
        tracing.score(trace_id, f"judge.{name}", value, comment=scores.critique if name == "judge_mean" else None)
    await asyncio.to_thread(tracing.flush)
    return out
