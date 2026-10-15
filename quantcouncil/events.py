"""Run event bus on Redis Streams; SSE readers resume from ``Last-Event-ID``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis

from quantcouncil.api.schemas import RunEvent, RunEventType

MAXLEN = 20_000
DONE_TTL_SECONDS = 7 * 24 * 3600


def stream_key(run_id: str) -> str:
    return f"quantcouncil:run:{run_id}:events"


class EventBus:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def publish(self, run_id: str, type_: RunEventType | str, data: dict[str, Any] | None = None) -> str:
        event = RunEvent(type=RunEventType(type_), run_id=run_id, ts=datetime.now(UTC), data=data or {})
        event_id = await self.redis.xadd(stream_key(run_id), {"e": event.model_dump_json()},
                                         maxlen=MAXLEN, approximate=True)
        if event.type == RunEventType.done:
            await self.redis.expire(stream_key(run_id), DONE_TTL_SECONDS)
        return event_id.decode() if isinstance(event_id, bytes) else event_id

    async def read(self, run_id: str, last_id: str = "0", block_ms: int = 15_000,
                   count: int = 500) -> list[tuple[str, dict]]:
        """Events after ``last_id``; blocks up to ``block_ms`` when there are none yet."""
        resp = await self.redis.xread({stream_key(run_id): last_id}, count=count, block=block_ms)
        out = []
        for _key, entries in resp or []:
            for entry_id, fields in entries:
                raw = fields.get(b"e") or fields.get("e")
                eid = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
                out.append((eid, json.loads(raw)))
        return out

    async def history(self, run_id: str) -> list[tuple[str, dict]]:
        entries = await self.redis.xrange(stream_key(run_id))
        return [((i.decode() if isinstance(i, bytes) else i), json.loads(f.get(b"e") or f.get("e")))
                for i, f in entries]
