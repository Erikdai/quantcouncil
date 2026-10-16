from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ResearchCreate(BaseModel):
    ticker: str
    question: str = Field(min_length=10, max_length=1200)
    as_of: date | None = None
    language: Literal["zh", "en"] = "zh"

    @field_validator("question", "ticker", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class ResearchPlan(BaseModel):
    subquestions: list[str] = Field(min_length=2, max_length=5)
    search_queries: list[str] = Field(
        min_length=2, max_length=6, description="English SEC filing search phrases"
    )
    metrics: list[
        Literal[
            "revenue",
            "operating_income",
            "net_income",
            "operating_cash_flow",
            "capex",
            "cash",
            "assets",
            "repurchases",
            "dividends",
        ]
    ] = Field(max_length=5)


class Evidence(BaseModel):
    id: str
    kind: Literal["filing", "financial", "calculation"]
    title: str
    url: str
    filed: str
    content: str
    accession: str | None = None
    sha256: str | None = None
    inputs: list[str] = Field(default_factory=list)
    data: dict = Field(default_factory=dict)


class Citation(BaseModel):
    source_id: str
    quote: str = Field(
        min_length=12,
        max_length=600,
        description="Exact verbatim excerpt from this source, no ellipsis",
    )


class Finding(BaseModel):
    text: str = Field(min_length=10)
    kind: Literal["fact", "inference"]
    citations: list[Citation] = Field(min_length=1, max_length=4)


class ResearchReport(BaseModel):
    title: str
    verdict: Literal["supported", "mixed", "not_supported", "insufficient"] = Field(
        description="Evidence support for answer.text, NOT a yes/no answer to the question. A well-evidenced negative answer is supported. mixed means conflicting evidence for the answer; insufficient means evidence cannot resolve it; not_supported means the draft answer itself lacks support and needs review."
    )
    answer: Finding
    findings: list[Finding] = Field(min_length=2, max_length=8)
    counterarguments: list[Finding] = Field(min_length=1, max_length=5)
    unknowns: list[str] = Field(min_length=1, max_length=6)
    what_would_change: list[str] = Field(min_length=1, max_length=5)


class ResearchSummary(BaseModel):
    id: str
    ticker: str
    question: str
    as_of: date
    language: str
    status: str
    stage: str
    created_at: datetime
    updated_at: datetime
    error: str | None = None

    model_config = {"from_attributes": True}


class ResearchDetail(ResearchSummary):
    plan: dict | None = None
    report: dict | None = None
    sources: list[dict] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    model: dict = Field(default_factory=dict)
    verification: dict | None = None

    manifest: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
