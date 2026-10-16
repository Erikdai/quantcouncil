"""Relational schema. LangGraph's checkpoint and store tables are created by their own ``setup()``."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 512  # BAAI/bge-small-zh-v1.5; change with a migration if the model changes

Money = Numeric(20, 4)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Run(TimestampMixin, Base):
    """One analysis of one ticker on one date, from request to decision and fill."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str | None] = mapped_column(String(128))
    market: Mapped[str] = mapped_column(String(8))
    trade_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), index=True)
    analysts: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    auto_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    account_id: Mapped[str] = mapped_column(String(64), default="default")
    source: Mapped[str] = mapped_column(String(16), default="api")  # api | schedule | eval
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    rating: Mapped[str | None] = mapped_column(String(16))
    reports: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    investment_debate: Mapped[str | None] = mapped_column(Text)
    risk_debate: Mapped[str | None] = mapped_column(Text)
    investment_plan: Mapped[str | None] = mapped_column(Text)
    trader_plan: Mapped[str | None] = mapped_column(Text)
    final_decision: Mapped[str | None] = mapped_column(Text)
    risk_check: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    approval: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    execution: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(64))

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    evals: Mapped[list[EvalResult]] = relationship(back_populates="run", cascade="all, delete-orphan",
                                                   order_by="EvalResult.id")


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    cash: Mapped[Decimal] = mapped_column(Money)
    initial_cash: Mapped[Decimal] = mapped_column(Money)
    peak_equity: Mapped[Decimal] = mapped_column(Money)


class Position(Base):
    """Holdings per account and ticker. ``locked_*`` implements T+1: shares bought
    on ``locked_date`` cannot be sold until the next session."""

    __tablename__ = "positions"

    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    avg_cost: Mapped[Decimal] = mapped_column(Money, default=0)
    locked_quantity: Mapped[int] = mapped_column(Integer, default=0)
    locked_date: Mapped[date | None] = mapped_column(Date)
    last_price: Mapped[Decimal | None] = mapped_column(Money)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())

    def available(self, on: date) -> int:
        return self.quantity - (self.locked_quantity if self.locked_date == on else 0)


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(4))
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(Money)
    fees: Mapped[Decimal] = mapped_column(Money, default=0)
    fee_detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    trade_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16))  # filled | rejected
    comment: Mapped[str | None] = mapped_column(Text)


class LedgerEntry(TimestampMixin, Base):
    """Append-only, hash-chained journal of every cash and position movement."""

    __tablename__ = "ledger_entries"
    __table_args__ = (UniqueConstraint("account_id", "seq"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))  # open | fill | reset
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class WatchItem(Base):
    __tablename__ = "watchlist"

    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(TimestampMixin, Base):
    """A source document in the research corpus: an exchange announcement or a broker report."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(Text)
    doc_type: Mapped[str] = mapped_column(String(32))  # announcement | research | news
    source: Mapped[str] = mapped_column(String(32))    # cninfo | eastmoney
    url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[date | None] = mapped_column(Date, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    chunks: Mapped[list[Chunk]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_embedding_hnsw", "embedding", postgresql_using="hnsw",
              postgresql_with={"m": 16, "ef_construction": 64},
              postgresql_ops={"embedding": "vector_cosine_ops"}),
        Index("ix_chunks_tokens_gin", "tokens", postgresql_using="gin"),
        Index("ix_chunks_ticker_published", "ticker", "published_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str | None] = mapped_column(String(32))
    published_at: Mapped[date | None] = mapped_column(Date)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    # jieba-segmented text indexed with the 'simple' config: Postgres full-text
    # search has no Chinese parser, so segmentation happens at write time.
    tokens: Mapped[Any] = mapped_column(TSVECTOR)
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM))

    document: Mapped[Document] = relationship(back_populates="chunks")


class EvalResult(TimestampMixin, Base):
    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    evaluator: Mapped[str] = mapped_column(String(64))
    scores: Mapped[dict[str, Any]] = mapped_column(JSONB)
    passed: Mapped[bool] = mapped_column(Boolean)
    comment: Mapped[str | None] = mapped_column(Text)

    run: Mapped[Run] = relationship(back_populates="evals")


class AppSetting(Base):
    """Key-value settings saved from the UI (secrets inside are encrypted by their owner)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


class ResearchJob(TimestampMixin, Base):
    """One question, its pinned model settings, evidence snapshots and final report."""

    __tablename__ = 'research_jobs'

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    question: Mapped[str] = mapped_column(Text)
    as_of: Mapped[date] = mapped_column(Date)
    language: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(24), index=True)
    stage: Mapped[str] = mapped_column(Text)
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    sources: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    events: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    model: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    manifest: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ThesisTimestampMixin(TimestampMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ThesisExtraction(ThesisTimestampMixin, Base):
    __tablename__ = "thesis_extractions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_job_id: Mapped[str] = mapped_column(ForeignKey("research_jobs.id"), index=True)
    status: Mapped[str] = mapped_column(String(24))
    report_hash: Mapped[str] = mapped_column(String(64))
    candidates: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    outputs: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    model: Mapped[dict[str, Any]] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)


class Thesis(ThesisTimestampMixin, Base):
    __tablename__ = "theses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    lifecycle: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    judgment: Mapped[str | None] = mapped_column(String(24))
    data_health: Mapped[str] = mapped_column(String(24), default="unknown")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_review_id: Mapped[str | None] = mapped_column(String(36))


class ThesisVersion(ThesisTimestampMixin, Base):
    __tablename__ = "thesis_versions"
    __table_args__ = (UniqueConstraint("thesis_id", "number"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    thesis_id: Mapped[str] = mapped_column(ForeignKey("theses.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    statement: Mapped[str] = mapped_column(Text)
    horizon: Mapped[str] = mapped_column(Text)
    rule: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    origin: Mapped[dict[str, Any]] = mapped_column(JSONB)
    contract_hash: Mapped[str] = mapped_column(String(64))
    model: Mapped[dict[str, Any]] = mapped_column(JSONB)
    meaning_review: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    baseline_review_id: Mapped[str | None] = mapped_column(String(36))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ThesisReview(ThesisTimestampMixin, Base):
    __tablename__ = "thesis_reviews"
    __table_args__ = (
        UniqueConstraint("version_id", "evidence_key"),
        Index(
            "uq_thesis_live_review", "thesis_id", unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    thesis_id: Mapped[str] = mapped_column(ForeignKey("theses.id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("thesis_versions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), index=True)
    as_of: Mapped[date] = mapped_column(Date)
    evidence_key: Mapped[str | None] = mapped_column(String(64))
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    outputs: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    unread: Mapped[bool] = mapped_column(Boolean, default=False)
