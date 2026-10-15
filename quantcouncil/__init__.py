"""QuantCouncil: A-share multi-agent research and paper-trading platform built on TradingAgents."""

import asyncio
import sys

__version__ = "0.1.0a1"

# psycopg's async driver cannot run on Windows' default Proactor loop.
if sys.platform == "win32":  # pragma: no cover - platform specific
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
