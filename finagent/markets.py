"""Market detection and the agent-core config for a run (vendors, benchmark, analysts, language)."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from tradingagents.dataflows.vendors.cn import (
    CN_BENCHMARK_MAP,
    CN_DATA_VENDORS,
    canonical_symbol,
    is_a_share,
)
from tradingagents.default_config import DEFAULT_CONFIG

CN, US = "CN", "US"

# API analyst names -> core analyst keys, per market.
ANALYSTS = {
    CN: {"market": "market", "sentiment": "cn_capital", "news": "news", "fundamentals": "fundamentals"},
    US: {"market": "market", "sentiment": "social", "news": "news", "fundamentals": "fundamentals"},
}
DEFAULT_ANALYSTS = ["market", "sentiment", "news", "fundamentals"]


@dataclass(frozen=True)
class Instrument:
    ticker: str   # canonical: 600519.SS / 000001.SZ / NVDA
    market: str   # CN or US

    @property
    def is_cn(self) -> bool:
        return self.market == CN


# Stands for "the A-share market" where a config is needed without a specific stock.
CN_DEFAULT = Instrument("000300.SS", CN)


def resolve_instrument(raw: str) -> Instrument:
    """Canonicalize a user-typed ticker and tell its market."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("ticker is empty")
    if is_a_share(text):
        return Instrument(canonical_symbol(text), CN)
    return Instrument(text.upper(), US)


def display_name(instrument: Instrument) -> str | None:
    """Short company name for display (A-shares only; blocking I/O, best effort)."""
    if not instrument.is_cn:
        return None
    try:
        from tradingagents.dataflows.vendors.cn.fundamentals import get_cn_profile  # noqa: PLC0415

        name = get_cn_profile(instrument.ticker).get("A股简称")
        return "".join(name.split()) if name else None  # cninfo pads some names: "五 粮 液"
    except Exception:  # noqa: BLE001
        return None


def core_analysts(market: str, requested: list[str] | None) -> list[str]:
    """Map API analyst names to the core's keys, keeping the request's order."""
    names = requested or DEFAULT_ANALYSTS
    table = ANALYSTS[market]
    unknown = [n for n in names if n not in table and n not in table.values()]
    if unknown:
        raise ValueError(f"unknown analyst(s) {unknown}; choose from {list(table)}")
    keys = [table.get(n, n) for n in names]
    return list(dict.fromkeys(keys))


def latest_trading_day(market: str, today: date | None = None) -> date:
    """The most recent completed session date (weekday fallback when offline).

    For A-shares the CSI 300's last bar is the authority, so exchange holidays
    (Spring Festival, National Day) are handled without a calendar table.
    """
    today = today or date.today()
    if market == CN:
        try:
            from tradingagents.dataflows.vendors.cn.market import load_cn_ohlcv  # noqa: PLC0415

            bars = load_cn_ohlcv("000300.SS", today.isoformat(), fill_gaps=False)
            return bars["Date"].iloc[-1].date()
        except Exception:  # noqa: BLE001 — fall back to the weekday rule
            pass
    day = today
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def agent_config(instrument: Instrument, *, data_dir: str | os.PathLike | None = None,
                 overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """The agent-core config for a run on ``instrument``.

    Starts from the core defaults (which already fold in ``TRADINGAGENTS_*``
    env vars such as the LLM provider and models), then applies the market.
    """
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    base = Path(data_dir or os.getenv("FINAGENT_DATA_DIR", ".finagent"))
    cfg.update(
        results_dir=str(base / "results"),
        data_cache_dir=str(base / "cache"),
        memory_log_path=str(base / "memory" / "trading_memory.md"),
    )
    # Provider overload (429/503) is common at peak hours; the SDKs back off and retry.
    if cfg.get("llm_max_retries") is None:
        cfg["llm_max_retries"] = 6
    if instrument.is_cn:
        cfg["data_vendors"] = {**cfg["data_vendors"], **CN_DATA_VENDORS}
        cfg["benchmark_map"] = {**cfg["benchmark_map"], **CN_BENCHMARK_MAP}
        cfg["global_news_lookback_days"] = 3
        if os.getenv("TRADINGAGENTS_OUTPUT_LANGUAGE") is None:
            cfg["output_language"] = "Simplified Chinese"
    for key, value in (overrides or {}).items():
        if value is not None:
            cfg[key] = value
    return cfg
