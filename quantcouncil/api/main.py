"""QuantCouncil HTTP API. Long work runs on Taskiq workers; progress streams back over SSE."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

import quantcouncil
from quantcouncil.api.routers import market, portfolio, reports, research, runs, settings
from quantcouncil.api.schemas import HealthOut
from quantcouncil.config import get_settings
from quantcouncil.db import get_engine
from quantcouncil.runtime import get_runtime
from quantcouncil.worker.broker import broker

logger = logging.getLogger("quantcouncil.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # The API runs graphs itself only with the in-process broker; otherwise workers do.
    await get_runtime().start(with_tools=settings.broker == "memory")
    if not broker.is_worker_process:
        await broker.startup()
    yield
    if not broker.is_worker_process:
        await broker.shutdown()
    await get_runtime().stop()


app = FastAPI(title="QuantCouncil API", version=quantcouncil.__version__, lifespan=lifespan,
              description="A-share multi-agent research and paper trading: runs, live events (SSE), approvals, "
                          "portfolio, research assistant (RAG + MCP + skills).")
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    if not request.url.path.endswith("/events"):
        logger.info("%s %s %s %.0fms rid=%s", request.method, request.url.path, response.status_code,
                    (time.perf_counter() - start) * 1000, request_id)
    return response


for module in (runs, portfolio, market, research, settings, reports):
    app.include_router(module.router)


@app.get("/api/health", response_model=HealthOut, tags=["health"])
async def health() -> HealthOut:
    settings = get_settings()
    services: dict[str, str] = {}
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("select 1"))
        services["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001
        services["postgres"] = f"error: {type(exc).__name__}"
    try:
        await get_runtime().redis.ping()
        services["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        services["redis"] = f"error: {type(exc).__name__}"
    if settings.mcp_enabled:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(settings.mcp_url.rsplit("/mcp", 1)[0] + "/healthz")
                services["mcp"] = "ok" if r.status_code == 200 else f"http {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            services["mcp"] = f"unreachable: {type(exc).__name__}"
    services["langfuse"] = "enabled" if settings.langfuse_enabled else "disabled"
    services["broker"] = settings.broker
    degraded = any(v.startswith(("error", "unreachable")) for k, v in services.items() if k in ("postgres", "redis"))
    return HealthOut(status="degraded" if degraded else "ok", version=quantcouncil.__version__, services=services)
