"""China A-share vendors (AKShare, BaoStock).

Enable them for a run with ``config["data_vendors"].update(CN_DATA_VENDORS)``.
"""

from tradingagents.dataflows.vendors.cn.common import (
    CN_INDICES,
    DEFAULT_CN_BENCHMARK,
    AShare,
    canonical_symbol,
    is_a_share,
    is_cn_index,
    limit_prices,
    parse_a_share,
    price_limit_pct,
    set_cache_backend,
)

# Vendor chains for an A-share run. Prices fall back from AKShare's sources to
# BaoStock; the US-only enrichment categories fall through to their defaults.
CN_DATA_VENDORS = {
    "core_stock_apis": "akshare,baostock",
    "technical_indicators": "akshare,baostock",
    "fundamental_data": "akshare",
    "news_data": "akshare",
    "macro_data": "akshare,fred",
}

# Alpha for an A-share decision is measured against the CSI 300.
CN_BENCHMARK_MAP = {".SS": DEFAULT_CN_BENCHMARK, ".SZ": DEFAULT_CN_BENCHMARK, ".BJ": DEFAULT_CN_BENCHMARK}

CN_VENDOR_NAMES = frozenset({"akshare", "baostock"})

__all__ = [
    "CN_BENCHMARK_MAP",
    "CN_DATA_VENDORS",
    "CN_INDICES",
    "CN_VENDOR_NAMES",
    "DEFAULT_CN_BENCHMARK",
    "AShare",
    "canonical_symbol",
    "is_a_share",
    "is_cn_index",
    "limit_prices",
    "parse_a_share",
    "price_limit_pct",
    "set_cache_backend",
]
