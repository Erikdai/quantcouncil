"""Langfuse tracing and scores; a no-op unless the Langfuse keys are set."""

from __future__ import annotations

import contextlib
import logging
from functools import lru_cache
from typing import Any

from quantcouncil.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def client():
    settings = get_settings()
    if not settings.langfuse_enabled:
        return None
    try:
        from langfuse import Langfuse  # noqa: PLC0415

        return Langfuse(public_key=settings.langfuse_public_key, secret_key=settings.langfuse_secret_key,
                        base_url=settings.langfuse_host or None, environment=settings.env)
    except Exception as exc:  # noqa: BLE001 — observability must not take the app down
        logger.warning("Langfuse disabled: %s", exc)
        return None


def trace_id_for(seed: str) -> str | None:
    lf = client()
    return lf.create_trace_id(seed=seed) if lf else None


def callbacks(trace_id: str | None) -> list:
    """LangChain callback handler bound to ``trace_id`` (empty when tracing is off)."""
    lf = client()
    if lf is None or trace_id is None:
        return []
    from langfuse.langchain import CallbackHandler  # noqa: PLC0415

    return [CallbackHandler(public_key=get_settings().langfuse_public_key, trace_context={"trace_id": trace_id})]


def run_config(*, trace_id: str | None, name: str, session_id: str, user_id: str | None = None,
               tags: list[str] | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """RunnableConfig fragments that name the trace and group it by session (the run or chat)."""
    md = {"langfuse_session_id": session_id, "langfuse_trace_name": name, "langfuse_tags": tags or []}
    if user_id:
        md["langfuse_user_id"] = user_id
    return {"callbacks": callbacks(trace_id), "metadata": {**md, **(metadata or {})}}


def trace_url(trace_id: str | None) -> str | None:
    lf = client()
    if lf is None or trace_id is None:
        return None
    try:
        return lf.get_trace_url(trace_id=trace_id)
    except Exception:  # noqa: BLE001
        host = get_settings().langfuse_host or "http://localhost:3000"
        return f"{host}/trace/{trace_id}"


def score(trace_id: str | None, name: str, value: float, comment: str | None = None) -> None:
    lf = client()
    if lf is None or trace_id is None:
        return
    try:
        lf.create_score(name=name, value=value, trace_id=trace_id, comment=comment, data_type="NUMERIC")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Langfuse score failed: %s", exc)


def flush() -> None:
    lf = client()
    if lf is not None:
        with contextlib.suppress(Exception):
            lf.flush()
