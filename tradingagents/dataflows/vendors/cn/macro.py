"""China macro series (LPR, M2/M1, CPI, PMI), filtered by publication date."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import pandas as pd

from tradingagents.dataflows.errors import NoMarketDataError
from tradingagents.dataflows.vendors.cn.common import akshare, cached, call_vendor

ALIASES = {
    "cn_lpr": "lpr", "lpr": "lpr", "china_lpr": "lpr",
    "cn_m2": "money", "m2": "money", "china_m2": "money", "cn_money_supply": "money",
    "cn_cpi": "cpi", "china_cpi": "cpi",
    "cn_pmi": "pmi", "china_pmi": "pmi", "pmi": "pmi",
}


@cached(ttl=12 * 3600, namespace="macro")
def _series(kind: str) -> pd.DataFrame:
    """A normalized frame: ``published`` (date), ``period`` (label), value columns."""
    ak = akshare()
    if kind == "lpr":
        df = call_vendor("china lpr", ak.macro_china_lpr)
        df = df.rename(columns={"TRADE_DATE": "published", "LPR1Y": "LPR 1Y (%)", "LPR5Y": "LPR 5Y (%)"})
        df["published"] = pd.to_datetime(df["published"], errors="coerce")
        df["period"] = df["published"].dt.strftime("%Y-%m-%d")
        return df[["published", "period", "LPR 1Y (%)", "LPR 5Y (%)"]].dropna(subset=["LPR 1Y (%)"])
    if kind == "money":
        df = call_vendor("china money supply", ak.macro_china_money_supply)

        def month_end(label: str):
            m = re.match(r"(\d{4})年(\d{2})月", str(label))
            return pd.Timestamp(int(m.group(1)), int(m.group(2)), 1) + pd.offsets.MonthEnd(0) if m else pd.NaT

        df["period_end"] = df["月份"].map(month_end)
        # PBoC publishes monetary aggregates around the 15th of the next month.
        df["published"] = df["period_end"] + pd.Timedelta(days=15)
        df["period"] = df["period_end"].dt.strftime("%Y-%m")
        df = df.rename(columns={"货币和准货币(M2)-同比增长": "M2 YoY (%)", "货币(M1)-同比增长": "M1 YoY (%)"})
        return df[["published", "period", "M2 YoY (%)", "M1 YoY (%)"]]
    if kind in ("cpi", "pmi"):
        fn = ak.macro_china_cpi_yearly if kind == "cpi" else ak.macro_china_pmi_yearly
        df = call_vendor(f"china {kind}", fn)
        df = df.rename(columns={"日期": "published", "今值": "value", "预测值": "consensus", "前值": "previous"})
        df["published"] = pd.to_datetime(df["published"], errors="coerce")
        df["period"] = df["published"].dt.strftime("%Y-%m-%d")
        label = "CPI YoY (%)" if kind == "cpi" else "Manufacturing PMI"
        df = df.rename(columns={"value": label})
        return df[["published", "period", label, "consensus", "previous"]].dropna(subset=[label])
    raise ValueError(kind)


def get_cn_macro(indicator: str, as_of_date: str, look_back_days: int | None = None) -> str:
    kind = ALIASES.get(str(indicator).strip().lower())
    if kind is None:
        # Not a China series: let the router try the next macro vendor (FRED).
        raise NoMarketDataError(indicator, indicator, "not a China macro alias (cn_lpr, cn_m2, cn_cpi, cn_pmi)")
    look_back_days = 365 if look_back_days is None else look_back_days
    end = datetime.strptime(as_of_date, "%Y-%m-%d")
    start = end - timedelta(days=look_back_days)
    df = _series(kind)
    df = df[(df["published"] <= pd.Timestamp(end)) & (df["published"] >= pd.Timestamp(start))]
    df = df.sort_values("published")
    if df.empty:
        raise NoMarketDataError(indicator, kind, f"no observations published {start:%Y-%m-%d}..{as_of_date}")
    value_cols = [c for c in df.columns if c not in ("published", "period")]
    lines = [f"# China macro: {kind.upper()} (published by {as_of_date}, last {look_back_days} days)", "",
             "| Period | Published | " + " | ".join(value_cols) + " |",
             "|---|---|" + "---:|" * len(value_cols)]
    for _, r in df.tail(24).iterrows():
        cells = ["" if pd.isna(r[c]) else f"{float(r[c]):.2f}" for c in value_cols]
        lines.append(f"| {r['period']} | {r['published']:%Y-%m-%d} | " + " | ".join(cells) + " |")
    return "\n".join(lines)
