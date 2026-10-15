"""Against the docker-compose Postgres and Redis:  pytest -m integration tests/finagent

    docker compose up -d postgres redis && alembic upgrade head
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import update

import finagent  # noqa: F401  (Windows event-loop policy)
from finagent.api.schemas import OrderProposal
from finagent.config import FeeSchedule
from finagent.db import get_engine, get_sessionmaker, session_scope
from finagent.db.models import LedgerEntry, Position
from finagent.portfolio import ledger

pytestmark = pytest.mark.integration

D1, D2 = date(2026, 10, 13), date(2026, 10, 14)
FEES = FeeSchedule(slippage_bps=0)


@pytest.fixture(autouse=True)
async def _isolate():
    """Delete the runs and accounts a test creates, so the shared dev database stays clean."""
    from sqlalchemy import delete, select  # noqa: PLC0415

    from finagent.db.models import Account, Run  # noqa: PLC0415

    async with session_scope() as s:
        runs_before = set((await s.execute(select(Run.id))).scalars())
        accounts_before = set((await s.execute(select(Account.id))).scalars())
    yield
    async with session_scope() as s:
        new_runs = set((await s.execute(select(Run.id))).scalars()) - runs_before
        new_accounts = set((await s.execute(select(Account.id))).scalars()) - accounts_before
        if new_runs:
            await s.execute(delete(Run).where(Run.id.in_(new_runs)))
        if new_accounts:
            await s.execute(delete(Account).where(Account.id.in_(new_accounts)))
    if new_runs:
        from redis.asyncio import Redis  # noqa: PLC0415

        from finagent.config import get_settings  # noqa: PLC0415
        from finagent.events import stream_key  # noqa: PLC0415

        redis = Redis.from_url(get_settings().redis_url)
        await redis.delete(*(stream_key(r) for r in new_runs))
        await redis.aclose()
    await get_engine().dispose()  # each test has its own event loop


def order(side, qty, price=100.0):
    return OrderProposal(ticker="600519.SS", side=side, quantity=qty, price=price, notional=qty * price,
                         est_fees=0, target_weight=0.1, current_weight=0)


async def test_ledger_fees_t_plus_one_idempotency_and_tamper_detection():
    acct = f"test-{uuid.uuid4().hex[:8]}"
    async with session_scope() as s:
        buy = await ledger.execute(s, acct, order("buy", 1000), D1, None, 1_000_000, fees=FEES)
    assert buy.status == "filled" and buy.fees["total"] == 26.0  # 25 commission + 1 transfer
    assert buy.cash_after == pytest.approx(1_000_000 - 100_000 - 26)

    async with session_scope() as s:
        same_day = await ledger.execute(s, acct, order("sell", 500), D1, None, 1_000_000, fees=FEES)
        view = await ledger.book_view(s, acct, D1, 1_000_000)
    assert same_day.status == "rejected" and "T+1" in same_day.reason
    assert view.positions["600519.SS"].available == 0

    run_id = None
    async with session_scope() as s:
        sell = await ledger.execute(s, acct, order("sell", 500), D2, run_id, 1_000_000, fees=FEES)
    assert sell.status == "filled" and sell.fees["stamp_duty"] == 25.0

    async with session_scope() as s:
        pos = await s.get(Position, (acct, "600519.SS"))
        assert pos.quantity == 500 and pos.available(D2) == 500
        assert await ledger.verify_chain(s, acct)

    # Editing any journaled amount breaks the hash chain.
    async with session_scope() as s:
        await s.execute(update(LedgerEntry).where(LedgerEntry.account_id == acct, LedgerEntry.seq == 2)
                        .values(payload={"tampered": True}))
    async with get_sessionmaker()() as s:
        assert not await ledger.verify_chain(s, acct)


async def test_execution_is_idempotent_per_run():
    acct = f"test-{uuid.uuid4().hex[:8]}"
    run_id = str(uuid.uuid4())
    async with session_scope() as s:
        from finagent.db.models import Run  # noqa: PLC0415

        s.add(Run(id=run_id, ticker="600519.SS", market="CN", trade_date=D1, status="running", analysts=[],
                  options={}, reports={}))
    async with session_scope() as s:
        first = await ledger.execute(s, acct, order("buy", 100), D1, run_id, 1_000_000, fees=FEES)
    async with session_scope() as s:
        again = await ledger.execute(s, acct, order("buy", 100), D1, run_id, 1_000_000, fees=FEES)
        account = await ledger.ensure_account(s, acct, 1_000_000)
    assert again.order_id == first.order_id and again.reason == "already executed"
    assert account.cash == Decimal("1000000") - Decimal("10000") - Decimal("5.10")


# --- API ------------------------------------------------------------------------------------

@pytest.fixture
async def api(monkeypatch):
    from finagent.api.main import app  # noqa: PLC0415
    from finagent.runtime import get_runtime  # noqa: PLC0415
    from finagent.worker import tasks  # noqa: PLC0415

    queued = []

    async def fake_kiq(*args):
        queued.append(args)
        return type("T", (), {"task_id": "t-1"})()

    monkeypatch.setattr(tasks.run_analysis, "kiq", fake_kiq)
    rt = await get_runtime().start(with_tools=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, queued, rt
    await rt.stop()


async def test_api_end_to_end_without_llm(api, monkeypatch):
    client, queued, rt = api
    from finagent.api.routers import runs as runs_router  # noqa: PLC0415

    monkeypatch.setattr(runs_router, "display_name", lambda instrument: "贵州茅台")

    health = (await client.get("/api/health")).json()
    assert health["services"]["postgres"] == "ok" and health["services"]["redis"] == "ok"

    skills = (await client.get("/api/skills")).json()
    assert any(s["name"] == "a-share-trading-rules" for s in skills)
    assert "T+1" in (await client.get("/api/skills/a-share-trading-rules")).json()["body"]

    acct = f"api-{uuid.uuid4().hex[:6]}"
    pf = (await client.post(f"/api/portfolio/reset?account_id={acct}", json={"initial_cash": 500000})).json()
    assert pf["account"]["equity"] == 500000 and pf["ledger_verified"]

    r = await client.post("/api/runs", json={"ticker": "sh600519", "trade_date": "2026-10-14",
                                             "analysts": ["market", "sentiment"]})
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["ticker"] == "600519.SS" and run["status"] == "queued" and run["name"] == "贵州茅台"
    assert queued and queued[0][0] == run["id"]

    assert (await client.post(f"/api/runs/{run['id']}/approval", json={"action": "approve"})).status_code == 409
    assert (await client.post("/api/runs", json={"ticker": "600519", "analysts": ["astrology"]})).status_code == 422
    listed = (await client.get("/api/runs?limit=5")).json()
    assert listed[0]["id"] == run["id"]

    # SSE replays the stream and closes on "done".
    await rt.bus.publish(run["id"], "status", {"status": "failed"})
    await rt.bus.publish(run["id"], "done", {"status": "failed"})
    async with client.stream("GET", f"/api/runs/{run['id']}/events") as resp:
        body = (await resp.aread()).decode()
    events = [line.split(":", 1)[1].strip() for line in body.splitlines() if line.startswith("event:")]
    assert events[0] == "status" and events[-1] == "done"
    data = [json.loads(line.split(":", 1)[1]) for line in body.splitlines() if line.startswith("data:")]
    assert data[-1]["data"]["status"] == "failed"

    wl = (await client.post("/api/watchlist", json={"ticker": "300750"})).json()
    assert wl["ticker"] == "300750.SZ"
    assert (await client.delete("/api/watchlist/300750")).status_code == 204


async def test_blocking_event_reads_survive_redis_default_timeout():
    """redis-py 8 times out socket reads after 5 s; a long XREAD must not raise."""
    from finagent.runtime import Runtime  # noqa: PLC0415

    rt = await Runtime().start(with_tools=False)
    try:
        assert await rt.bus.read(f"idle-{uuid.uuid4().hex[:6]}", block_ms=6500) == []
    finally:
        await rt.stop()


async def test_llm_settings_api_never_returns_keys(api):
    from finagent.db.models import AppSetting  # noqa: PLC0415

    async with session_scope() as s:
        row = await s.get(AppSetting, "llm")
        saved_before = dict(row.value) if row else None
    client, _, _ = api
    try:
        catalog = (await client.get("/api/settings/llm/catalog")).json()
        assert {p["id"] for p in catalog} == {"deepseek", "openai", "anthropic"}
        body = {"provider": "openai", "quick_model": "gpt-6-luna", "deep_model": "gpt-6-sol", "temperature": 0.3,
                "max_debate_rounds": 2, "max_risk_rounds": 1, "output_language": "English",
                "api_key": "sk-integration-test-key-123456"}
        saved = (await client.put("/api/settings/llm", json=body)).json()
        assert saved["provider"] == "openai" and saved["max_debate_rounds"] == 2
        assert saved["keys"]["openai"] == {"set": True, "source": "ui", "hint": "sk-int...3456"}
        assert "sk-integration-test-key-123456" not in str(saved)
        kept = (await client.put("/api/settings/llm", json={**body, "api_key": None, "temperature": 0.5})).json()
        assert kept["keys"]["openai"]["source"] == "ui" and kept["temperature"] == 0.5
        cleared = (await client.put("/api/settings/llm", json={**body, "api_key": None, "clear_key": True})).json()
        assert cleared["keys"]["openai"]["source"] != "ui"
    finally:  # leave the shared database's settings as they were
        async with session_scope() as s:
            row = await s.get(AppSetting, "llm")
            if saved_before is None and row is not None:
                await s.delete(row)
            elif saved_before is not None:
                row.value = saved_before
