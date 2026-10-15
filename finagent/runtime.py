"""Process-wide resources: psycopg pool, LangGraph checkpointer and store, Redis, MCP tools."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from redis import Redis as SyncRedis
from redis.asyncio import Redis

from finagent.config import get_settings
from finagent.events import EventBus
from finagent.memory.store import index_config
from tradingagents.dataflows.vendors.cn import set_cache_backend

logger = logging.getLogger(__name__)


class RedisCache:
    """Shared market-data cache for the China vendors (sync: they run in worker threads)."""

    def __init__(self, url: str):
        self.client = SyncRedis.from_url(url, socket_timeout=2, socket_connect_timeout=2)

    def get(self, key: str) -> bytes | None:
        return self.client.get(key)

    def set(self, key: str, value: bytes, ttl: int) -> None:
        self.client.set(key, value, ex=ttl)


@dataclass
class Runtime:
    pool: AsyncConnectionPool | None = None
    checkpointer: AsyncPostgresSaver | None = None
    store: AsyncPostgresStore | None = None
    redis: Redis | None = None
    bus: EventBus | None = None
    tool_source: str = "none"
    started: bool = False
    status: dict[str, str] = field(default_factory=dict)

    async def start(self, *, with_tools: bool = True) -> Runtime:
        if self.started:
            return self
        settings = get_settings()
        # Blocking XREADs (SSE) outlast redis-py's default 5 s socket timeout.
        self.redis = Redis.from_url(settings.redis_url, socket_timeout=None, health_check_interval=30)
        self.bus = EventBus(self.redis)
        try:
            set_cache_backend(RedisCache(settings.redis_url))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis market-data cache unavailable, using in-process cache: %s", exc)
        self.pool = AsyncConnectionPool(settings.psycopg_url, open=False, max_size=20,
                                        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
        await self.pool.open(wait=True, timeout=30)
        self.checkpointer = AsyncPostgresSaver(self.pool)
        await self.checkpointer.setup()
        self.store = AsyncPostgresStore(self.pool, index=index_config(settings.embedding_dim))
        await self.store.setup()
        if with_tools:
            await self.register_tools()
        self.started = True
        return self

    async def register_tools(self) -> None:
        """Give the A-share capital analyst its tools: MCP first, in-process fallback."""
        from finagent.graph import cn_capital_analyst  # noqa: PLC0415
        from finagent.graph.local_tools import LOCAL_TOOLS  # noqa: PLC0415

        settings = get_settings()
        tools = []
        if settings.mcp_enabled:
            try:
                from finagent.mcp_client import load_tools  # noqa: PLC0415

                tools = await load_tools(list(cn_capital_analyst.TOOL_NAMES))
                self.tool_source = f"mcp ({settings.mcp_url}, {len(tools)} tools)"
            except Exception as exc:  # noqa: BLE001
                logger.warning("MCP server unreachable (%s); using in-process tools", exc)
        if not tools:
            tools = LOCAL_TOOLS
            self.tool_source = f"local ({len(tools)} tools)"
        cn_capital_analyst.register(tools)
        logger.info("A-share capital analyst tools: %s", self.tool_source)

    async def stop(self) -> None:
        if self.pool is not None:
            await self.pool.close()
        if self.redis is not None:
            await self.redis.aclose()
        self.started = False


_runtime = Runtime()


def get_runtime() -> Runtime:
    return _runtime
