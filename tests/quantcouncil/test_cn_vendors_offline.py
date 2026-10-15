"""The China vendors against a fake akshare: point-in-time cut-offs, fallback and routing."""

import copy
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from tradingagents.dataflows import router
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.errors import NoMarketDataError, VendorUnavailableError
from tradingagents.dataflows.vendors.cn import (
    CN_DATA_VENDORS,
    capital,
    common,
    fundamentals,
    macro,
    market,
    news,
)
from tradingagents.default_config import DEFAULT_CONFIG

pytestmark = pytest.mark.unit


def bars(end: str, n: int = 260) -> pd.DataFrame:
    days = pd.bdate_range(end=end, periods=n)
    close = pd.Series(range(n), dtype=float) + 100
    return pd.DataFrame({"date": days.date, "open": close, "high": close + 1, "low": close - 1, "close": close,
                         "volume": 1e6, "amount": 1e8})


@pytest.fixture(autouse=True)
def fresh_cache():
    common.set_cache_backend(common.MemoryCache())
    yield
    common.set_cache_backend(common.MemoryCache())


@pytest.fixture
def fake_ak(monkeypatch):
    ak = SimpleNamespace()
    for module in (common, market, fundamentals, news, macro, capital):
        monkeypatch.setattr(module, "akshare", lambda: ak)
    return ak


def test_bars_never_go_past_the_analysis_date(fake_ak):
    today = date.today()
    fake_ak.stock_zh_a_daily = lambda **k: bars(today.isoformat())
    as_of = (today - timedelta(days=30)).isoformat()
    df = market.load_cn_ohlcv("600519", as_of)
    assert df["Date"].max() <= pd.Timestamp(as_of)


def test_sina_failure_falls_back_to_tencent(fake_ak):
    def boom(**k):
        raise ConnectionError("reset by peer")

    fake_ak.stock_zh_a_daily = boom
    fake_ak.stock_zh_a_hist_tx = lambda **k: bars(date.today().isoformat())
    df = market._fetch_akshare.uncached("600519.SS", "2024-01-01", date.today().isoformat(), "qfq")
    assert len(df) == 260


def test_all_sources_down_is_vendor_unavailable(fake_ak, monkeypatch):
    monkeypatch.setattr(common.time, "sleep", lambda s: None)

    def boom(**k):
        raise ConnectionError("reset by peer")

    fake_ak.stock_zh_a_daily = fake_ak.stock_zh_a_hist_tx = fake_ak.stock_zh_a_hist = boom
    with pytest.raises(VendorUnavailableError):
        market.load_cn_ohlcv("600519", date.today().isoformat())


def test_stale_bars_are_refused(fake_ak):
    fake_ak.stock_zh_a_daily = lambda **k: bars("2026-01-05")
    with pytest.raises(NoMarketDataError, match="stale|suspended"):
        market.load_cn_ohlcv("600519", "2026-03-02")


def test_statements_are_served_as_published(fake_ak):
    frame = pd.DataFrame({
        "REPORT_DATE": ["2026-06-30", "2026-03-31", "2025-12-31"],
        "NOTICE_DATE": ["2026-08-15", "2026-04-25", "2026-04-17"],
        "REPORT_TYPE": ["中报", "一季报", "年报"],
        "REPORT_DATE_NAME": ["2026中报", "2026一季报", "2025年报"],
        "TOTAL_OPERATE_INCOME": [9.2e10, 5.4e10, 1.7e11], "TOTAL_OPERATE_INCOME_YOY": [1.3, 6.3, -1.2],
        "PARENT_NETPROFIT": [4.4e10, 2.7e10, 8.2e10], "BASIC_EPS": [35.6, 21.8, 65.9],
    })
    fake_ak.stock_profit_sheet_by_report_em = lambda symbol: frame
    before = fundamentals.get_cn_income_statement("600519", "quarterly", "2026-08-01")
    after = fundamentals.get_cn_income_statement("600519", "quarterly", "2026-08-20")
    assert "2026中报" not in before and "2026一季报" in before
    assert "2026中报" in after


def test_disclosure_deadlines_pick_the_shareholder_period():
    assert fundamentals._latest_disclosed_period("2026-10-14") == "20260630"
    assert fundamentals._latest_disclosed_period("2026-04-29") == "20250930"
    assert fundamentals._latest_disclosed_period("2026-05-01") == "20260331"


def test_unknown_macro_alias_defers_to_the_next_vendor():
    with pytest.raises(NoMarketDataError):
        macro.get_cn_macro("fed_funds_rate", "2026-10-14")


def test_router_serves_a_shares_from_china_vendors_only_when_configured(fake_ak):
    fake_ak.stock_zh_a_daily = lambda **k: bars(date.today().isoformat())
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    assert not router.cn_market_active("600519.SS")  # default config: Yahoo
    cfg["data_vendors"].update(CN_DATA_VENDORS)
    with run_config(cfg):
        assert router.cn_market_active("600519.SS")
        assert not router.cn_market_active("NVDA")
        out = router.route_to_vendor("get_stock_data", "600519.SS", "2026-01-01", date.today().isoformat())
        assert out.startswith("# A-share daily bars for 600519.SS")
        snap = router.verified_snapshot("600519.SS", date.today().isoformat(), 5)
        assert "Verified market data snapshot for 600519.SS" in snap
