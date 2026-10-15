"""A-share daily bars, technical indicators and the verified snapshot.

The ``akshare`` vendor tries Sina, Tencent, then Eastmoney (which refuses many
non-mainland IPs); ``baostock`` is a separate vendor. Bars are forward-adjusted
for analysis; the risk engine reads unadjusted bars, since price limits apply to
traded prices.
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta

import pandas as pd
from stockstats import wrap

from tradingagents.dataflows.errors import NoMarketDataError, VendorError, VendorUnavailableError
from tradingagents.dataflows.vendors.cn.common import (
    CN_INDICES,
    akshare,
    cached,
    call_vendor,
    canonical_symbol,
    is_cn_index,
    parse_a_share,
    ymd,
)

logger = logging.getLogger(__name__)

# Days a vendor's latest bar may trail the requested date before it is stale.
# Spans the Spring Festival and National Day closures (up to 9 calendar days).
MAX_STALE_DAYS = 12
_OHLCV_COLUMNS = ["Date", "Open", "High", "Low", "Close", "Volume", "Amount"]

INDICATOR_NOTES: dict[str, str] = {
    "close_50_sma": "50-day SMA: medium-term trend and dynamic support/resistance; lags price.",
    "close_200_sma": "200-day SMA: long-term trend benchmark; golden/death cross reference.",
    "close_10_ema": "10-day EMA: responsive short-term momentum; noisy in choppy markets.",
    "macd": "MACD line (12/26 EMA difference): momentum and trend changes via crossovers.",
    "macds": "MACD signal (9 EMA of MACD): crossovers with the MACD line trigger signals.",
    "macdh": "MACD histogram: gap between MACD and its signal; early divergence.",
    "rsi": "RSI(14): overbought >70 / oversold <30; can stay extreme in strong trends.",
    "boll": "Bollinger middle band (20 SMA): dynamic benchmark for price.",
    "boll_ub": "Bollinger upper band (+2 sd): overbought / breakout zone.",
    "boll_lb": "Bollinger lower band (-2 sd): oversold zone.",
    "atr": "ATR(14): volatility for stop distance and position sizing.",
    "vwma": "Volume-weighted MA: confirms trend with volume.",
    "mfi": "Money Flow Index: volume-weighted RSI; >80 overbought, <20 oversold.",
}


def _frame(df: pd.DataFrame, mapping: dict[str, str], volume_scale: float = 1.0) -> pd.DataFrame:
    """Rename a vendor frame to the shared OHLCV columns, parse dates, sort."""
    out = df.rename(columns=mapping)
    missing = [c for c in ("Date", "Open", "High", "Low", "Close") if c not in out.columns]
    if missing:
        raise VendorUnavailableError(f"bar frame lacks {missing}; got {list(df.columns)[:10]}")
    out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    out = out.dropna(subset=["Date"])
    for col in ("Open", "High", "Low", "Close", "Volume", "Amount"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
        else:
            out[col] = float("nan")
    if volume_scale != 1.0:
        out["Volume"] = out["Volume"] * volume_scale
    return out[_OHLCV_COLUMNS].sort_values("Date").reset_index(drop=True)


def _sina(symbol: str, start: str, end: str, adjust: str) -> pd.DataFrame:
    s = parse_a_share(symbol)
    df = call_vendor("sina daily", lambda: akshare().stock_zh_a_daily(
        symbol=s.prefixed, start_date=ymd(start), end_date=ymd(end), adjust=adjust))
    return _frame(df, {"date": "Date", "open": "Open", "high": "High", "low": "Low",
                       "close": "Close", "volume": "Volume", "amount": "Amount"})


def _tencent(symbol: str, start: str, end: str, adjust: str) -> pd.DataFrame:
    s = parse_a_share(symbol)
    df = call_vendor("tencent daily", lambda: akshare().stock_zh_a_hist_tx(
        symbol=s.prefixed, start_date=ymd(start), end_date=ymd(end), adjust=adjust))
    return _frame(df, {"date": "Date", "open": "Open", "high": "High", "low": "Low",
                       "close": "Close", "volume": "Volume", "amount": "Amount"})


def _eastmoney(symbol: str, start: str, end: str, adjust: str) -> pd.DataFrame:
    s = parse_a_share(symbol)
    df = call_vendor("eastmoney daily", lambda: akshare().stock_zh_a_hist(
        symbol=s.code, period="daily", start_date=ymd(start), end_date=ymd(end), adjust=adjust),
        attempts=1)
    # Eastmoney reports volume in board lots of 100 shares.
    return _frame(df, {"日期": "Date", "开盘": "Open", "最高": "High", "最低": "Low",
                       "收盘": "Close", "成交量": "Volume", "成交额": "Amount"}, volume_scale=100.0)


def _index(symbol: str, start: str, end: str, adjust: str) -> pd.DataFrame:
    prefixed, _ = CN_INDICES[canonical_symbol(symbol)]
    df = call_vendor("sina index daily", lambda: akshare().stock_zh_index_daily(symbol=prefixed))
    out = _frame(df, {"date": "Date", "open": "Open", "high": "High", "low": "Low",
                      "close": "Close", "volume": "Volume"})
    return out[(out["Date"] >= pd.Timestamp(start)) & (out["Date"] <= pd.Timestamp(end))]


_AKSHARE_SOURCES = (("sina", _sina), ("tencent", _tencent), ("eastmoney", _eastmoney))


@cached(ttl=900, namespace="ohlcv-akshare")
def _fetch_akshare(symbol: str, start: str, end: str, adjust: str) -> pd.DataFrame:
    """Bars from the first akshare source that answers with rows."""
    if is_cn_index(symbol):
        return _index(symbol, start, end, adjust)
    errors = []
    for name, source in _AKSHARE_SOURCES:
        try:
            df = source(symbol, start, end, adjust)
        except VendorError as exc:
            errors.append(f"{name}: {exc}")
            continue
        if not df.empty:
            return df
        errors.append(f"{name}: no rows")
    raise VendorUnavailableError("; ".join(errors))


# --- BaoStock -------------------------------------------------------------------
# BaoStock keeps one login session per process and is not thread-safe.
_bs_lock = threading.Lock()
_bs_logged_in = False


def _bs_query(fn_name: str, *args, **kwargs) -> pd.DataFrame:
    global _bs_logged_in
    import baostock as bs  # noqa: PLC0415

    with _bs_lock:
        if not _bs_logged_in:
            lg = bs.login()
            if lg.error_code != "0":
                raise VendorUnavailableError(f"baostock login failed: {lg.error_msg}")
            _bs_logged_in = True
        rs = getattr(bs, fn_name)(*args, **kwargs)
        if rs.error_code != "0":
            # A dropped session reports an error; log in again next call.
            _bs_logged_in = False
            raise VendorUnavailableError(f"baostock {fn_name}: {rs.error_msg}")
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        return pd.DataFrame(rows, columns=rs.fields)


@cached(ttl=900, namespace="ohlcv-baostock")
def _fetch_baostock(symbol: str, start: str, end: str, adjust: str) -> pd.DataFrame:
    s = parse_a_share(symbol)
    flag = {"qfq": "2", "hfq": "1", "": "3"}[adjust]
    df = call_vendor("baostock k-data", lambda: _bs_query(
        "query_history_k_data_plus", s.baostock, "date,open,high,low,close,volume,amount",
        start_date=start, end_date=end, frequency="d", adjustflag=flag), attempts=2)
    return _frame(df, {"date": "Date", "open": "Open", "high": "High", "low": "Low",
                       "close": "Close", "volume": "Volume", "amount": "Amount"})


_FETCHERS = {"akshare": _fetch_akshare, "baostock": _fetch_baostock}


def _window_start(as_of_date: str) -> str:
    """Three years before the analysis date, at a year start so calls share a cache entry."""
    as_of = datetime.strptime(as_of_date, "%Y-%m-%d").date()
    return date(as_of.year - 3, 1, 1).isoformat()


def load_cn_ohlcv(symbol: str, as_of_date: str, *, vendor: str = "akshare",
                  adjust: str = "qfq", fill_gaps: bool = True) -> pd.DataFrame:
    """Daily bars up to and including ``as_of_date`` (never after it).

    Raises NoMarketDataError for no rows or a stale frame, VendorUnavailableError
    when the vendor could not answer. ``fill_gaps`` forward-fills suspended days'
    missing prices so indicators compute on a continuous series.
    """
    canonical = canonical_symbol(symbol)
    today = date.today().isoformat()
    df = _FETCHERS[vendor](canonical, _window_start(as_of_date), today, adjust)
    if df is None or df.empty:
        raise NoMarketDataError(symbol, canonical, "no daily bars")
    cutoff = pd.Timestamp(as_of_date)
    df = df[df["Date"] <= cutoff].copy()
    if df.empty:
        raise NoMarketDataError(symbol, canonical, f"no bars on or before {as_of_date}")
    stale = (cutoff - df["Date"].max()).days
    if stale > MAX_STALE_DAYS:
        raise NoMarketDataError(
            symbol, canonical,
            f"latest bar is {df['Date'].max().date()}, {stale} days before {as_of_date} "
            "(suspended, delisted or stale vendor data)")
    if fill_gaps:
        df = df.dropna(subset=["Close"])
        df[["Open", "High", "Low", "Close"]] = df[["Open", "High", "Low", "Close"]].ffill()
    return df.reset_index(drop=True)


def get_cn_closes(symbol: str, start_date: str, end_date: str) -> pd.Series:
    """Closes from ``start_date`` up to, not including, ``end_date`` (settlement's contract)."""
    last = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        df = load_cn_ohlcv(symbol, min(last, date.today().isoformat()))
    except NoMarketDataError:
        return pd.Series(dtype=float)
    df = df[df["Date"] >= pd.Timestamp(start_date)]
    return pd.Series(df["Close"].to_numpy(), index=pd.DatetimeIndex(df["Date"]), name="Close")


# --- Router-facing vendor functions --------------------------------------------

def _stock_data(symbol: str, start_date: str, end_date: str, vendor: str) -> str:
    df = load_cn_ohlcv(symbol, end_date, vendor=vendor, fill_gaps=False)
    df = df[df["Date"] >= pd.Timestamp(start_date)]
    if df.empty:
        raise NoMarketDataError(symbol, canonical_symbol(symbol), f"no bars between {start_date} and {end_date}")
    out = df.copy()
    out["Date"] = out["Date"].dt.strftime("%Y-%m-%d")
    for col in ("Open", "High", "Low", "Close"):
        out[col] = out[col].round(2)
    header = (f"# A-share daily bars for {canonical_symbol(symbol)} from {start_date} to {end_date} "
              f"(forward-adjusted 前复权, CNY; Volume in shares, Amount in CNY)\n"
              f"# Total records: {len(out)}\n\n")
    return header + out.to_csv(index=False)


def get_cn_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    return _stock_data(symbol, start_date, end_date, "akshare")


def get_cn_stock_data_baostock(symbol: str, start_date: str, end_date: str) -> str:
    return _stock_data(symbol, start_date, end_date, "baostock")


def _indicator_window(symbol: str, indicator: str, as_of_date: str, look_back_days: int, vendor: str) -> str:
    if indicator not in INDICATOR_NOTES:
        raise ValueError(f"Indicator {indicator} is not supported. Please choose from: {list(INDICATOR_NOTES)}")
    df = load_cn_ohlcv(symbol, as_of_date, vendor=vendor)
    stock = wrap(df.copy())
    stock[indicator]  # noqa: B018 — stockstats computes the column on access
    values = {d.strftime("%Y-%m-%d"): v for d, v in zip(df["Date"], stock[indicator], strict=False)}
    end = datetime.strptime(as_of_date, "%Y-%m-%d")
    lines = []
    for i in range(look_back_days + 1):
        day = (end - timedelta(days=i)).strftime("%Y-%m-%d")
        value = values.get(day)
        if value is None:
            lines.append(f"{day}: N/A: Not a trading day (weekend, holiday or suspension)")
        else:
            lines.append(f"{day}: {'N/A' if pd.isna(value) else round(float(value), 4)}")
    start = (end - timedelta(days=look_back_days)).strftime("%Y-%m-%d")
    return (f"## {indicator} values from {start} to {as_of_date}:\n\n" + "\n".join(lines)
            + "\n\n" + INDICATOR_NOTES[indicator])


def get_cn_indicator_window(symbol: str, indicator: str, as_of_date: str, look_back_days: int) -> str:
    return _indicator_window(symbol, indicator, as_of_date, look_back_days, "akshare")


def get_cn_indicator_window_baostock(symbol: str, indicator: str, as_of_date: str, look_back_days: int) -> str:
    return _indicator_window(symbol, indicator, as_of_date, look_back_days, "baostock")


def build_cn_snapshot(symbol: str, as_of_date: str, look_back_days: int = 30) -> str:
    """The verified snapshot (same layout as the Yahoo one) from A-share bars."""
    from tradingagents.dataflows.vendors.yahoo.snapshot import build_verified_market_snapshot  # noqa: PLC0415

    return build_verified_market_snapshot(
        canonical_symbol(symbol), as_of_date, look_back_days,
        loader=lambda sym, day, fill_gaps=True: load_cn_ohlcv(sym, day, fill_gaps=fill_gaps),
    )


def build_cn_snapshot_baostock(symbol: str, as_of_date: str, look_back_days: int = 30) -> str:
    from tradingagents.dataflows.vendors.yahoo.snapshot import build_verified_market_snapshot  # noqa: PLC0415

    return build_verified_market_snapshot(
        canonical_symbol(symbol), as_of_date, look_back_days,
        loader=lambda sym, day, fill_gaps=True: load_cn_ohlcv(sym, day, vendor="baostock", fill_gaps=fill_gaps),
    )


def latest_bar(symbol: str, as_of_date: str) -> dict:
    """Unadjusted last bar and the previous close, for price-limit and fill checks."""
    df = load_cn_ohlcv(symbol, as_of_date, adjust="", fill_gaps=False).dropna(subset=["Close"])
    if len(df) < 2:
        raise NoMarketDataError(symbol, canonical_symbol(symbol), "fewer than two bars")
    last, prev = df.iloc[-1], df.iloc[-2]
    return {
        "date": last["Date"].strftime("%Y-%m-%d"),
        "open": float(last["Open"]), "high": float(last["High"]), "low": float(last["Low"]),
        "close": float(last["Close"]), "volume": float(last["Volume"]),
        "prev_close": float(prev["Close"]),
    }
