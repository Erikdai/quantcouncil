"""Long-term semantic memory on the LangGraph Postgres store: decisions and settled lessons."""

from __future__ import annotations

import logging
import re
from typing import Any

from langgraph.store.base import BaseStore

logger = logging.getLogger(__name__)

LESSONS = ("lessons",)


def decisions_ns(ticker: str) -> tuple[str, ...]:
    # Store namespace labels may not contain periods (600519.SS -> 600519_SS).
    return ("decisions", ticker.replace(".", "_"))


def index_config(dims: int) -> dict[str, Any]:
    from finagent.rag.models import LocalEmbeddings  # noqa: PLC0415

    return {"dims": dims, "embed": LocalEmbeddings(), "fields": ["text"]}


def _summary(decision: str, limit: int = 600) -> str:
    text = re.sub(r"\s+", " ", decision or "").strip()
    return text[:limit]


async def remember_decision(store: BaseStore, *, run_id: str, ticker: str, trade_date: str, rating: str,
                            decision: str, situation: str) -> None:
    await store.aput(decisions_ns(ticker), run_id, {
        "text": f"{ticker} {trade_date} {rating}. Situation: {situation[:400]} Decision: {_summary(decision)}",
        "ticker": ticker, "trade_date": trade_date, "rating": rating, "run_id": run_id,
    })


async def sync_lessons(store: BaseStore, memory_log) -> int:
    """Copy settled reflections from the core's memory log into the semantic index (idempotent)."""
    count = 0
    for entry in memory_log.load_entries():
        if entry.get("pending") or not entry.get("reflection"):
            continue
        key = f"{entry['ticker']}:{entry['date']}"
        await store.aput(LESSONS, key, {
            "text": f"{entry['ticker']} {entry['date']} rated {entry.get('rating')}; "
                    f"outcome {entry.get('raw', '')} raw, {entry.get('alpha', '')} alpha. "
                    f"Lesson: {entry['reflection']}",
            "ticker": entry["ticker"], "trade_date": entry["date"], "rating": entry.get("rating"),
            "resolved": entry.get("resolved"),
        })
        count += 1
    return count


async def recall(store: BaseStore, *, query: str, ticker: str, as_of: str, limit: int = 4) -> list[str]:
    """Lessons from similar situations, known by ``as_of`` (point-in-time), other tickers first."""
    try:
        hits = await store.asearch(LESSONS, query=query, limit=limit * 3)
    except Exception as exc:  # noqa: BLE001 — memory is advisory; never fail a run on it
        logger.warning("semantic recall failed: %s", exc)
        return []
    out = []
    for item in hits:
        v = item.value
        resolved = v.get("resolved") or v.get("trade_date")
        if resolved and str(resolved) > as_of:
            continue
        out.append(f"[similarity {item.score:.2f}] {v['text']}" if item.score is not None else v["text"])
        if len(out) >= limit:
            break
    return out

