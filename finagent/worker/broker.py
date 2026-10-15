"""Taskiq broker and scheduler on Redis (``FINAGENT_BROKER=memory`` runs tasks in-process)."""

from __future__ import annotations

import logging

from taskiq import InMemoryBroker, TaskiqEvents, TaskiqScheduler, TaskiqState
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

from finagent.config import get_settings
from finagent.runtime import get_runtime

logger = logging.getLogger(__name__)

_settings = get_settings()

if _settings.broker == "memory":
    broker = InMemoryBroker()
else:
    # BRPOP blocks until a task arrives; redis-py's default 5 s socket timeout would kill the worker.
    broker = ListQueueBroker(_settings.redis_url, queue_name="finagent", socket_timeout=None,
                             health_check_interval=30).with_result_backend(
        RedisAsyncResultBackend(_settings.redis_url, result_ex_time=24 * 3600))

scheduler = TaskiqScheduler(broker, sources=[LabelScheduleSource(broker)])


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _startup(state: TaskiqState) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    await get_runtime().start(with_tools=True)
    logger.info("worker runtime ready (tools: %s)", get_runtime().tool_source)


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def _shutdown(state: TaskiqState) -> None:
    await get_runtime().stop()
