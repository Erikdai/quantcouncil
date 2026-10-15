"""LLM settings: provider, models, keys (write-only) and analysis depth, editable from the UI."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter
from pydantic import BaseModel

from finagent import llm_settings as llm
from finagent.api.deps import SessionDep
from finagent.markets import CN_DEFAULT, agent_config

router = APIRouter(prefix="/api/settings", tags=["settings"])


class ProviderInfo(BaseModel):
    id: str
    label: str
    quick_models: list[str]
    deep_models: list[str]


class TestResult(BaseModel):
    ok: bool
    latency_ms: int | None = None
    model: str
    reply: str | None = None
    error: str | None = None


@router.get("/llm/catalog", response_model=list[ProviderInfo])
async def catalog() -> list[ProviderInfo]:
    models = llm.catalog()
    return [ProviderInfo(id=p, label=info["label"], quick_models=models[p]["quick"], deep_models=models[p]["deep"])
            for p, info in llm.PROVIDERS.items()]


@router.get("/llm", response_model=llm.LLMSettingsOut)
async def get_llm(session: SessionDep) -> llm.LLMSettingsOut:
    settings, keys = await llm.load(session)
    return llm.status(settings, keys)


@router.put("/llm", response_model=llm.LLMSettingsOut)
async def put_llm(body: llm.LLMSettingsIn, session: SessionDep) -> llm.LLMSettingsOut:
    await llm.save(session, body)
    await session.commit()
    return await get_llm(session)


@router.post("/llm/test", response_model=TestResult)
async def test_llm(body: llm.LLMSettingsIn, session: SessionDep) -> TestResult:
    """Send one short prompt with the form's settings (a typed key, else the saved or env key)."""
    from tradingagents.llm_clients import create_tier_client  # noqa: PLC0415

    _, keys = await llm.load(session)
    key = body.api_key or llm.api_key(body.provider, keys)[0]
    cfg = agent_config(CN_DEFAULT, overrides={**llm.overrides(body, key), "llm_max_retries": 0})

    def ping() -> str:
        model = create_tier_client(cfg, "quick", timeout=30).get_llm()
        reply = model.invoke("Reply with the single word OK.")
        content = reply.content if isinstance(reply.content, str) else str(reply.content)
        return content.strip()[:80]

    start = time.perf_counter()
    try:
        reply = await asyncio.to_thread(ping)
    except Exception as exc:  # noqa: BLE001 — report any provider error to the user
        return TestResult(ok=False, model=body.quick_model, error=f"{type(exc).__name__}: {str(exc)[:300]}")
    return TestResult(ok=True, model=body.quick_model, reply=reply,
                      latency_ms=int((time.perf_counter() - start) * 1000))
