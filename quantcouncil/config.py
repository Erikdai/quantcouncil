"""Platform settings from environment variables and ``.env``."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RiskLimits(BaseSettings):
    """Deterministic limits the risk gate enforces on every order (code, not prompts)."""

    model_config = SettingsConfigDict(env_prefix="RISK_", env_file=".env", extra="ignore")

    max_position_pct: float = Field(0.10, description="Max weight of one name in equity")
    max_gross_exposure_pct: float = Field(0.95, description="Max invested share of equity")
    min_cash_reserve: float = Field(1_000.0, description="Cash (CNY) never spent")
    max_drawdown_pct: float = Field(0.15, description="Block new buys beyond this drawdown from peak")
    max_orders_per_day: int = 20
    block_st: bool = Field(True, description="Refuse buys of ST / *ST names")
    lot_size: int = 100
    # Rating -> target weight, as a fraction of max_position_pct (Hold keeps the position).
    rating_targets: dict[str, float] = Field(
        default_factory=lambda: {"Buy": 1.0, "Overweight": 0.6, "Underweight": 0.5, "Sell": 0.0})


class FeeSchedule(BaseSettings):
    """A-share retail fee schedule used by the paper ledger."""

    model_config = SettingsConfigDict(env_prefix="FEE_", env_file=".env", extra="ignore")

    commission_rate: float = 0.00025    # broker commission, both sides
    commission_min: float = 5.0          # CNY minimum per order
    stamp_duty_rate: float = 0.0005      # sells only (since 2023-08-28)
    transfer_fee_rate: float = 0.00001   # both sides
    slippage_bps: float = 5.0            # paper fills pay this much past the reference price


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="QUANTCOUNCIL_", extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+psycopg://quantcouncil:quantcouncil@127.0.0.1:15432/quantcouncil"
    redis_url: str = "redis://:quantcouncil-redis@127.0.0.1:6379/0"
    # "redis" in deployment; "memory" runs tasks in-process (tests, single-process dev).
    broker: str = "redis"
    mcp_url: str = "http://127.0.0.1:8001/mcp"
    mcp_enabled: bool = True
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"])

    # Encrypts API keys saved from the UI; set a long random value in production.
    secret_key: str = "quantcouncil-dev-secret-change-me"

    initial_cash: float = 1_000_000.0
    default_account: str = "default"

    # RAG / memory embeddings (local ONNX via fastembed; no API key needed)
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_dim: int = 512
    reranker_model: str = "BAAI/bge-reranker-v2-m3-int8"  # empty string disables reranking
    model_cache_dir: str = ".cache/models"
    chunk_size: int = 500
    chunk_overlap: int = 80

    # Scheduled jobs (cron, Asia/Shanghai): scan the watchlist after the close.
    watchlist_scan_cron: str = "30 15 * * 1-5"
    settle_cron: str = "0 18 * * 1-5"

    # Observability: Langfuse is used when both keys are set.
    langfuse_public_key: str | None = Field(default=None, alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str | None = Field(default=None, alias="LANGFUSE_SECRET_KEY")
    langfuse_host: str | None = Field(default=None, alias="LANGFUSE_HOST")

    rate_limit_per_minute: int = 30

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def psycopg_url(self) -> str:
        """The URL in plain libpq form, for LangGraph's psycopg checkpointer and store."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def get_risk_limits() -> RiskLimits:
    return RiskLimits()


@lru_cache(maxsize=1)
def get_fee_schedule() -> FeeSchedule:
    return FeeSchedule()
