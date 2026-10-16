from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quantcouncil.deep_research.schemas import Citation, Evidence

Metric = Literal[
    "revenue",
    "operating_income",
    "net_income",
    "operating_cash_flow",
    "capex",
    "repurchases",
    "dividends",
    "operating_margin",
    "free_cash_flow",
]


class Rule(BaseModel):
    """Four bounded templates, never model-generated executable code."""

    model_config = ConfigDict(extra="forbid")
    template: Literal["trend", "threshold", "relative", "coverage"]
    period: Literal["annual", "latest_reported"]
    metric: Metric = "operating_cash_flow"
    operator: Literal["gt", "gte", "lt", "lte"] = "gt"
    threshold: Decimal | None = Field(default=None, allow_inf_nan=False)
    observations: int = Field(default=1, ge=1, le=3)
    target_segment: str | None = Field(default=None, max_length=180)
    coverage_expectation: Literal["covers", "shortfall"] = "covers"
    cash_outflows: list[Literal["capex", "repurchases", "dividends"]] = Field(
        default_factory=lambda: ["capex"], min_length=1, max_length=3
    )

    @model_validator(mode="after")
    def coherent(self):
        if self.template == "threshold" and self.threshold is None:
            raise ValueError("Threshold rules require an explicit threshold")
        if self.template != "threshold" and self.threshold is not None:
            raise ValueError("A threshold cannot be silently added to another template")
        if self.template == "relative" and (
            not self.target_segment or self.metric != "operating_income"
        ):
            raise ValueError(
                "Relative rules require operating_income and an exact segment identifier"
            )
        if self.template != "relative" and self.target_segment:
            raise ValueError("Segment selectors are only supported for relative operating income")
        if self.template != "trend" and self.observations != 1:
            raise ValueError("Repeated observations are only supported for trend rules")
        if self.template != "threshold" and self.operator != "gt":
            raise ValueError("Only threshold rules have an editable comparison operator")
        if len(set(self.cash_outflows)) != len(self.cash_outflows):
            raise ValueError("Cash expenses cannot be counted twice")
        if self.template != "coverage" and self.coverage_expectation != "covers":
            raise ValueError("Coverage direction only applies to the coverage template")
        if self.template != "coverage" and self.cash_outflows != ["capex"]:
            raise ValueError("Expense lists only apply to cash coverage")
        if self.template == "coverage" and self.metric != "operating_cash_flow":
            raise ValueError("Coverage uses operating cash flow, not accrual profit")
        return self


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin_path: str = Field(
        description="answer or findings.N; exact original finding, never a made-up paraphrase"
    )
    original_text: str
    statement: str = Field(min_length=10, max_length=1600)
    verification_class: Literal["quantitative", "qualitative", "not_verifiable"]
    relationship: Literal["direct", "partial", "proxy", "new_hypothesis"]
    rule: Rule | None
    suggested_assumptions: list[str]
    limitations: list[str]
    citations: list[Citation] = Field(min_length=1, max_length=4)


class CandidateBatch(BaseModel):
    candidates: list[Candidate] = Field(min_length=1, max_length=4)


class MeaningReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_matches_statement: bool
    relationship: Literal["direct", "partial", "proxy", "new_hypothesis"]
    issues: list[str]
    assumptions: list[str]
    explanation: str


class ScopeReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    citations: list[Citation] = Field(default_factory=list, max_length=4)
    roster_complete: bool = False
    comparable: bool
    issues: list[str]
    explanation: str


class ExtractionCreate(BaseModel):
    source_job_id: str


class VersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    extraction_id: str
    candidate_index: int = Field(ge=0, le=3)
    statement: str = Field(min_length=10, max_length=1600)
    rule: Rule | None
    horizon: Literal["until_paused"] = "until_paused"


class Confirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: str
    contract_hash: str
    acknowledge_baseline: Literal[True]
    accept_reformulation: bool = False
    start_monitoring: bool = True


class CheckCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of: date | None = None


class LifecycleChange(BaseModel):
    lifecycle: Literal["active", "paused", "archived"]


class Snapshot(BaseModel):
    ticker: str
    as_of: date
    fetched_at: str
    manifest: list[dict]
    sources: list[Evidence]
    excerpts: list[Evidence]
    fingerprint: str


class RevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str = Field(min_length=10, max_length=1600)
    rule: Rule | None
    horizon: Literal["until_paused"] = "until_paused"
