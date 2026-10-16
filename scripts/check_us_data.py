"""Probe real US data through MCP (no LLM key); write inspectable JSON evidence.

Run from the repository root: .venv/bin/python scripts/check_us_data.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

from quantcouncil.api.routers.market import kline
from quantcouncil.markets import latest_trading_day


async def main() -> int:
    day = latest_trading_day('US')
    client = MultiServerMCPClient({'market': {
        'transport': 'stdio', 'command': sys.executable,
        'args': ['-m', 'quantcouncil.mcp_server'],
    }})
    tools = {tool.name: tool for tool in await client.get_tools()}
    checks = {}
    for ticker in ('AAPL', 'NVDA'):
        try:
            chart = await kline(ticker, start=day - timedelta(days=30), end=day)
            checks[f'{ticker}_chart'] = {'ok': bool(chart.bars) and chart.latest_bar_date == str(day),
                                        **chart.model_dump(mode='json')}
        except Exception as exc:
            checks[f'{ticker}_chart'] = {'ok': False, 'error': str(exc)}
    requests = {
        'snapshot': ('get_market_snapshot', {'symbol': 'AAPL', 'as_of_date': str(day)}),
        'profile': ('get_company_fundamentals', {'symbol': 'AAPL', 'as_of_date': str(date.today())}),
        'news': ('get_company_news', {'symbol': 'AAPL', 'start_date': str(day - timedelta(days=7)), 'end_date': str(day)}),
        'income': ('get_financial_statement', {'symbol': 'AAPL', 'statement': 'income', 'as_of_date': str(day)}),
    }
    for label, (name, args) in requests.items():
        try:
            result = await asyncio.wait_for(tools[name].ainvoke(args), timeout=60)
            # MCP adapter content is a list of text blocks; preserve source output.
            content = result if isinstance(result, str) else '\n'.join(
                block.get('text', '') for block in result if isinstance(block, dict))
            unavailable = ('DATA_UNAVAILABLE', 'NO_DATA', 'INVALID_ARGUMENT', '<unavailable', 'withheld', 'coverage gap')
            checks[label] = {'ok': bool(content) and not any(s.lower() in content.lower() for s in unavailable),
                             'tool': name, 'args': args, 'content': content}
        except Exception as exc:
            checks[label] = {'ok': False, 'error': str(exc)}
    out = Path('reports/us-data-smoke.json')
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({'checked_at': datetime.now(UTC).isoformat(), 'session': str(day),
                               'checks': checks}, ensure_ascii=False, indent=2))
    for name, check in checks.items():
        print(f"{name}: {'PASS' if check['ok'] else 'UNAVAILABLE'}")
    print(f'Evidence: {out.resolve()}')
    return 0 if all(check['ok'] for check in checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
