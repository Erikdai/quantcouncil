"""User-configurable LLM settings: provider, models, sampling and debate depth.

Saved from the UI into ``app_settings``; API keys are Fernet-encrypted with a key
derived from ``QUANTCOUNCIL_SECRET_KEY`` and never returned, only a masked hint.
A provider without a saved key falls back to its environment variable.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any, Literal

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from quantcouncil.config import get_settings
from quantcouncil.db.models import AppSetting
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS

Provider = Literal["deepseek", "openai", "anthropic"]
PROVIDERS: dict[str, dict[str, str]] = {
    "deepseek": {"label": "DeepSeek", "key_env": "DEEPSEEK_API_KEY"},
    "openai": {"label": "OpenAI", "key_env": "OPENAI_API_KEY"},
    "anthropic": {"label": "Anthropic Claude", "key_env": "ANTHROPIC_API_KEY"},
}
SETTINGS_KEY = "llm"


class LLMSettings(BaseModel):
    provider: Provider = "deepseek"
    quick_model: str = "deepseek-flash"
    deep_model: str = "deepseek-v4-pro"
    base_url: str | None = Field(default=None, description="Override the provider's endpoint (proxy or gateway)")
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_debate_rounds: int = Field(default=1, ge=1, le=5)
    max_risk_rounds: int = Field(default=1, ge=1, le=5)
    output_language: Literal["auto", "Simplified Chinese", "English"] = "auto"


class LLMSettingsIn(LLMSettings):
    api_key: str | None = Field(default=None, description="New key for the provider; omit to keep the saved one")
    clear_key: bool = False


class KeyStatus(BaseModel):
    set: bool
    source: Literal["ui", "env"] | None = None
    hint: str | None = None


class LLMSettingsOut(LLMSettings):
    keys: dict[str, KeyStatus]


def env_defaults() -> LLMSettings:
    provider = os.getenv("TRADINGAGENTS_LLM_PROVIDER", "deepseek").lower()
    if provider not in PROVIDERS:
        provider = "deepseek"
    return LLMSettings(
        provider=provider,
        quick_model=os.getenv("TRADINGAGENTS_QUICK_THINK_LLM") or catalog()[provider]["quick"][0],
        deep_model=os.getenv("TRADINGAGENTS_DEEP_THINK_LLM") or catalog()[provider]["deep"][0],
        max_debate_rounds=DEFAULT_CONFIG.get("max_debate_rounds", 1),
        max_risk_rounds=DEFAULT_CONFIG.get("max_risk_discuss_rounds", 1),
    )


# Newer models listed ahead of the core's catalog.
EXTRA_MODELS = {"anthropic": {"quick": ["claude-haiku-5-5", "claude-sonnet-5-5"],
                              "deep": ["claude-sonnet-5-5", "claude-opus-5-5"]}}


def catalog() -> dict[str, dict[str, list[str]]]:
    """Model ids per provider and tier, from the core's catalog (the UI also accepts custom ids)."""
    out = {}
    for provider in PROVIDERS:
        tiers = MODEL_OPTIONS.get(provider, {})
        out[provider] = {}
        for tier in ("quick", "deep"):
            models = EXTRA_MODELS.get(provider, {}).get(tier, []) + [m for _, m in tiers.get(tier, [])]
            out[provider][tier] = [m for m in dict.fromkeys(models) if m != "custom"]
    return out


def _fernet() -> Fernet:
    secret = get_settings().secret_key.encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret).digest()))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:  # secret rotated: the key must be entered again
        return None


def mask(key: str) -> str:
    return f"{key[:6]}...{key[-4:]}" if len(key) > 12 else "****"


async def load(session: AsyncSession) -> tuple[LLMSettings, dict[str, str]]:
    """Saved settings (or env defaults) and the encrypted keys by provider."""
    row = await session.get(AppSetting, SETTINGS_KEY)
    if row is None:
        return env_defaults(), {}
    value = dict(row.value)
    keys = value.pop("keys", {})
    return LLMSettings.model_validate(value), keys


async def save(session: AsyncSession, data: LLMSettingsIn) -> None:
    _, keys = await load(session)
    if data.clear_key:
        keys.pop(data.provider, None)
    elif data.api_key:
        keys[data.provider] = encrypt(data.api_key.strip())
    value = LLMSettings.model_validate(data.model_dump()).model_dump()
    row = await session.get(AppSetting, SETTINGS_KEY)
    if row is None:
        session.add(AppSetting(key=SETTINGS_KEY, value={**value, "keys": keys}))
    else:
        row.value = {**value, "keys": keys}


def api_key(provider: str, keys: dict[str, str]) -> tuple[str | None, str | None]:
    """(key, source) for a provider: the UI-saved key, else its environment variable."""
    if provider in keys and (key := decrypt(keys[provider])):
        return key, "ui"
    env = os.getenv(PROVIDERS[provider]["key_env"])
    return (env, "env") if env else (None, None)


def status(settings: LLMSettings, keys: dict[str, str]) -> LLMSettingsOut:
    out = {}
    for provider in PROVIDERS:
        key, source = api_key(provider, keys)
        out[provider] = KeyStatus(set=bool(key), source=source, hint=mask(key) if key else None)
    return LLMSettingsOut(**settings.model_dump(), keys=out)


def overrides(settings: LLMSettings, key: str | None) -> dict[str, Any]:
    """Agent-core config overrides for a run (``None`` values keep the market defaults)."""
    return {
        "llm_provider": settings.provider,
        "quick_think_llm": settings.quick_model,
        "deep_think_llm": settings.deep_model,
        "backend_url": settings.base_url or None,
        "temperature": settings.temperature,
        "max_debate_rounds": settings.max_debate_rounds,
        "max_risk_discuss_rounds": settings.max_risk_rounds,
        "output_language": None if settings.output_language == "auto" else settings.output_language,
        "api_key": key,
    }


def fingerprint(settings: LLMSettings, key: str | None) -> str:
    raw = json.dumps({**settings.model_dump(), "key": hashlib.sha256((key or "").encode()).hexdigest()},
                     sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def resolve(session: AsyncSession, snapshot: dict | None = None) -> tuple[LLMSettings, dict[str, Any]]:
    """Settings for a run and their core overrides. ``snapshot`` pins a run to the
    settings it started with (resume and retry use the same models)."""
    current, keys = await load(session)
    settings = LLMSettings.model_validate(snapshot) if snapshot else current
    key, _ = api_key(settings.provider, keys)
    return settings, overrides(settings, key)
