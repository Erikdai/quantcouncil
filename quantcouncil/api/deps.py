"""Shared FastAPI dependencies: DB session, event bus, rate limiting."""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from quantcouncil.config import get_settings
from quantcouncil.db import get_session
from quantcouncil.events import EventBus
from quantcouncil.runtime import get_runtime


def get_bus() -> EventBus:
    bus = get_runtime().bus
    if bus is None:
        raise HTTPException(503, "event bus not ready")
    return bus


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def rate_limit(request: Request) -> None:
    """Fixed-window limit per client IP on expensive endpoints (LLM runs, chat), in Redis."""
    redis = get_runtime().redis
    if redis is None:
        return
    limit = get_settings().rate_limit_per_minute
    client = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown")
    key = f"quantcouncil:ratelimit:{client.split(',')[0].strip()}:{int(time.time() // 60)}"
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 70)
    except Exception:  # noqa: BLE001 — never block requests because Redis hiccuped
        return
    if count > limit:
        raise HTTPException(429, f"rate limit: {limit} requests per minute")


BusDep = Annotated[EventBus, Depends(get_bus)]
RateLimited = Depends(rate_limit)
