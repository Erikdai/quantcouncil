"""US platform boundaries: sessions, data routing, chart cutoff and currency isolation."""
from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from quantcouncil.api.routers import market as market_api
from quantcouncil.graph.runner import _portfolio_context
from quantcouncil.markets import latest_trading_day, resolve_instrument
from quantcouncil.mcp_server import server


@pytest.mark.parametrize(('instant', 'expected'), [
    ('2026-10-16T15:59:00-04:00', '2026-10-15'),
    ('2026-10-16T16:01:00-04:00', '2026-10-16'),
    ('2026-10-17T09:00:00+11:00', '2026-10-16'),
    ('2026-07-03T17:00:00-04:00', '2026-07-02'),  # Independence Day observed
    ('2026-11-27T12:59:00-05:00', '2026-11-25'),  # Thanksgiving + early close
    ('2026-11-27T13:01:00-05:00', '2026-11-27'),
    ('2026-03-09T19:59:00+00:00', '2026-03-06'),  # DST: close is now 20:00 UTC
    ('2026-03-09T20:01:00+00:00', '2026-03-09'),
])
def test_completed_us_session(instant, expected):
    assert str(latest_trading_day('US', now=datetime.fromisoformat(instant))) == expected


@pytest.mark.parametrize(('raw', 'canonical'), [('aapl', 'AAPL'), ('BRK.B', 'BRK-B'), ('BRK-A', 'BRK-A'), ('SPY', 'SPY')])
def test_us_symbols(raw, canonical):
    assert resolve_instrument(raw).ticker == canonical


@pytest.mark.parametrize('raw', ['0700.HK', '../AAPL', 'BTC-USD', '^GSPC', 'not a stock'])
def test_unsupported_symbols_are_not_mislabeled_us(raw):
    with pytest.raises(ValueError):
        resolve_instrument(raw)


async def test_shared_mcp_tools_route_to_us_vendors(monkeypatch):
    calls = []

    def fake(*args):
        calls.append(args)
        return 'source data'

    monkeypatch.setattr(server.us_market, 'get_YFin_data_online', fake)
    monkeypatch.setattr(server, 'build_verified_market_snapshot', fake)
    monkeypatch.setattr(server.us_market, 'get_stock_stats_indicators_window', fake)
    monkeypatch.setattr(server.us_fundamentals, 'get_fundamentals', fake)
    monkeypatch.setattr(server.sec_edgar, 'get_income_statement', fake)
    monkeypatch.setattr(server.us_news, 'get_news_yfinance', fake)
    assert await server.get_stock_bars('aapl', '2026-10-01', '2026-10-15') == 'source data'
    assert await server.get_market_snapshot('aapl', '2026-10-15') == 'source data'
    assert await server.get_technical_indicator('aapl', 'rsi', '2026-10-15') == 'source data'
    assert await server.get_company_fundamentals('aapl', '2026-10-15') == 'source data'
    assert await server.get_financial_statement('aapl', 'income', '2026-10-15') == 'source data'
    assert await server.get_company_news('aapl', '2026-10-01', '2026-10-15') == 'source data'
    assert all(args[0] == 'AAPL' for args in calls)
    assert calls[4] == ('AAPL', 'quarterly', '2026-10-15')


async def test_shared_mcp_still_routes_cn(monkeypatch):
    monkeypatch.setattr(server.market, 'build_cn_snapshot', lambda *args: str(args))
    assert '600519.SS' in await server.get_market_snapshot('600519', '2026-10-15')


async def test_us_chart_cutoff_and_metadata(monkeypatch):
    seen = []
    monkeypatch.setattr(market_api, 'latest_trading_day', lambda market: date(2026, 10, 15))

    def bars(ticker, market, start, end):
        seen.append((ticker, market, end))
        return [market_api.Bar(time='2026-10-15', open=100, high=102, low=99, close=101, volume=500)]

    monkeypatch.setattr(market_api, '_bars', bars)
    out = await market_api.kline('aapl', start=date(2026, 10, 1), end=date(2026, 10, 16))
    assert seen == [('AAPL', 'US', date(2026, 10, 15))]
    assert (out.currency, out.source, out.timezone) == ('USD', 'Yahoo Finance', 'America/New_York')
    assert out.latest_bar_date == '2026-10-15'


def test_chart_never_exposes_rows_after_end(monkeypatch):
    from tradingagents.dataflows.vendors.yahoo import ohlcv

    df = pd.DataFrame({'Date': pd.to_datetime(['2026-10-14', '2026-10-15', '2026-10-16']),
                       'Open': [1, 2, 3], 'High': [2, 3, 4], 'Low': [0, 1, 2],
                       'Close': [1, 2, 3], 'Volume': [10, 20, 30]})
    monkeypatch.setattr(ohlcv, 'load_ohlcv', lambda *a, **k: df)
    bars = market_api._bars('AAPL', 'US', date(2026, 10, 15), date(2026, 10, 15))
    assert [b.time for b in bars] == ['2026-10-15']


async def test_us_research_never_reads_cny_account():
    # No database is present: returning before I/O is part of the contract.
    assert await _portfolio_context(SimpleNamespace(market='US')) is None


async def test_us_historical_profile_is_withheld_without_network():
    result = await server.get_company_fundamentals('AAPL', '2020-01-01')
    assert 'withheld' in result


async def test_us_ingestion_is_rejected_before_queueing():
    from fastapi import HTTPException

    from quantcouncil.api.routers.research import ingest
    from quantcouncil.api.schemas import IngestRequest

    with pytest.raises(HTTPException) as caught:
        await ingest(IngestRequest(ticker='AAPL'))
    assert caught.value.status_code == 422


async def test_us_run_date_cannot_include_an_unfinished_session(monkeypatch):
    from fastapi import HTTPException

    from quantcouncil.api.routers import runs
    from quantcouncil.api.schemas import RunCreate

    monkeypatch.setattr(runs, 'latest_trading_day', lambda market: date(2026, 10, 15))
    with pytest.raises(HTTPException) as caught:
        await runs.create_run(RunCreate(ticker='AAPL', trade_date=date(2026, 10, 16)), None, None)
    assert caught.value.status_code == 422


async def test_kline_http_contract(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    app = FastAPI()
    app.include_router(market_api.router)
    monkeypatch.setattr(market_api, 'latest_trading_day', lambda market: date(2026, 10, 15))
    monkeypatch.setattr(market_api, '_bars', lambda *args: [])
    async with AsyncClient(transport=ASGITransport(app), base_url='http://test') as client:
        result = await client.get('/api/market/kline/NVDA')
        assert result.status_code == 200
        assert result.json()['currency'] == 'USD'
        invalid = await client.get('/api/market/kline/0700.HK')
        assert invalid.status_code == 422
