"""A-share money flow and sentiment: Dragon-Tiger list, margin balances, limit-up/down
breadth, sell-side research and main-force fund flow. Point-in-time on ``as_of_date``;
served to agents through the MCP server.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from tradingagents.dataflows.errors import NoMarketDataError
from tradingagents.dataflows.vendors.cn.common import (
    akshare,
    cached,
    call_vendor,
    canonical_symbol,
    parse_a_share,
    ymd,
)
from tradingagents.dataflows.vendors.cn.market import load_cn_ohlcv

YI = 1e8


def _num(value, fmt="{:,.2f}") -> str:
    try:
        return "N/A" if value is None or pd.isna(value) else fmt.format(float(value))
    except (TypeError, ValueError):
        return str(value)


def _trading_days(symbol: str, as_of_date: str, n: int) -> list[str]:
    """The last ``n`` sessions on or before ``as_of_date`` the stock traded."""
    df = load_cn_ohlcv(symbol, as_of_date, fill_gaps=False)
    return [d.strftime("%Y-%m-%d") for d in df["Date"].tail(n)]


@cached(ttl=6 * 3600, namespace="lhb")
def _lhb(start: str, end: str) -> pd.DataFrame:
    return call_vendor("eastmoney dragon-tiger", lambda: akshare().stock_lhb_detail_em(start_date=start, end_date=end))


def get_dragon_tiger(symbol: str, as_of_date: str, look_back_days: int = 30) -> str:
    s = parse_a_share(symbol)
    end = datetime.strptime(as_of_date, "%Y-%m-%d")
    start = end - timedelta(days=look_back_days)
    df = _lhb(start.strftime("%Y%m%d"), ymd(as_of_date))
    df = df[df["代码"].astype(str).str.zfill(6) == s.code]
    header = f"## 龙虎榜 Dragon-Tiger list for {s.canonical}, {start:%Y-%m-%d} to {as_of_date}\n"
    if df.empty:
        return header + "Not on the list in this window (no abnormal-move disclosure)."
    lines = ["| Date | Reason | Close | Chg % | Net buy (万) | Buy (万) | Sell (万) | Net/turnover % | Note |",
             "|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for _, r in df.sort_values("上榜日").iterrows():
        lines.append(
            f"| {r['上榜日']} | {r.get('上榜原因')} | {_num(r.get('收盘价'))} | {_num(r.get('涨跌幅'))} "
            f"| {_num((r.get('龙虎榜净买额') or 0) / 1e4, '{:,.0f}')} | {_num((r.get('龙虎榜买入额') or 0) / 1e4, '{:,.0f}')} "
            f"| {_num((r.get('龙虎榜卖出额') or 0) / 1e4, '{:,.0f}')} | {_num(r.get('净买额占总成交比'))} | {r.get('解读')} |")
    return header + "\n".join(lines) + (
        "\n\nNet buy is listed seats' buys minus sells; institutional seats buying on a limit-up day "
        "reads as conviction, hot-money seats (游资) as short-term speculation.")


@cached(ttl=7 * 24 * 3600, namespace="margin")
def _margin_day(exchange: str, day: str) -> pd.DataFrame:
    ak = akshare()
    if exchange == "SH":
        return call_vendor("sse margin", lambda: ak.stock_margin_detail_sse(date=day))
    return call_vendor("szse margin", lambda: ak.stock_margin_detail_szse(date=day))


def get_margin_trading(symbol: str, as_of_date: str, sessions: int = 5) -> str:
    s = parse_a_share(symbol)
    if s.exchange == "BJ":
        return f"## 融资融券 for {s.canonical}\nBeijing Stock Exchange margin data is not covered."
    rows = []
    for day in _trading_days(s.canonical, as_of_date, max(1, min(sessions, 10))):
        try:
            df = _margin_day(s.exchange, ymd(day))
        except Exception:  # noqa: BLE001 — one missing day should not sink the series
            continue
        code_col = "标的证券代码" if s.exchange == "SH" else "证券代码"
        hit = df[df[code_col].astype(str).str.zfill(6) == s.code]
        if not hit.empty:
            r = hit.iloc[0]
            rows.append((day, r.get("融资余额"), r.get("融资买入额"), r.get("融券余量")))
    header = f"## 融资融券 Margin balances for {s.canonical} (last {sessions} sessions to {as_of_date})\n"
    if not rows:
        return header + "Not a margin-eligible security, or no exchange data for these sessions."
    lines = ["| Date | Financing balance (亿) | Financing buys (亿) | Short shares outstanding |", "|---|---:|---:|---:|"]
    lines += [f"| {d} | {_num((b or 0) / YI)} | {_num((buy or 0) / YI)} | {_num(short, '{:,.0f}')} |"
              for d, b, buy, short in rows]
    first, last = rows[0][1], rows[-1][1]
    if first and last:
        lines.append(f"\nFinancing balance change over the window: {(float(last) / float(first) - 1) * 100:+.2f}%")
    return header + "\n".join(lines)


@cached(ttl=6 * 3600, namespace="limit-pool")
def _pool(kind: str, day: str) -> pd.DataFrame:
    ak = akshare()
    fn = ak.stock_zt_pool_em if kind == "up" else ak.stock_zt_pool_dtgc_em
    return call_vendor(f"eastmoney limit-{kind} pool", lambda: fn(date=day))


def get_market_breadth(as_of_date: str) -> str:
    """Limit-up / limit-down pools: how hot speculative risk appetite is that day."""
    day = ymd(as_of_date)
    up = _pool("up", day)
    down = _pool("down", day)
    if up.empty and down.empty:
        raise NoMarketDataError("market", "market", f"no limit pools for {as_of_date} (non-trading day?)")
    max_streak = int(pd.to_numeric(up.get("连板数"), errors="coerce").max()) if not up.empty else 0
    broken = int((pd.to_numeric(up.get("炸板次数"), errors="coerce") > 0).sum()) if not up.empty else 0
    industries = up["所属行业"].value_counts().head(5) if not up.empty else pd.Series(dtype=int)
    leaders = up.sort_values("连板数", ascending=False).head(5) if not up.empty else up
    lines = [f"## A-share market breadth on {as_of_date} (涨跌停池)",
             f"- Limit-up stocks: {len(up)}; limit-down stocks: {len(down)}",
             f"- Highest consecutive limit-up streak (连板高度): {max_streak}",
             f"- Limit-ups that broke and resealed at least once (炸板): {broken}",
             "- Industries with most limit-ups: " + ", ".join(f"{k} {v}" for k, v in industries.items()),
             "- Streak leaders: " + ", ".join(f"{r['名称']}({r['代码']}) {r['连板数']}板" for _, r in leaders.iterrows()),
             "",
             "Reading: many limit-ups and a tall streak mean strong speculative appetite; many limit-downs "
             "or frequent 炸板 mean risk-off and failing momentum."]
    return "\n".join(lines)


@cached(ttl=6 * 3600, namespace="research")
def research_reports_frame(code: str) -> pd.DataFrame:
    df = call_vendor("eastmoney research reports", lambda: akshare().stock_research_report_em(symbol=code))
    df = df.copy()
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    return df.dropna(subset=["日期"]).sort_values("日期", ascending=False)


def get_research_reports(symbol: str, as_of_date: str, look_back_days: int = 90, limit: int = 15) -> str:
    """Sell-side reports published in the window: institution, rating and EPS forecasts."""
    s = parse_a_share(symbol)
    df = research_reports_frame(s.code)
    end = pd.Timestamp(as_of_date)
    df = df[(df["日期"] <= end) & (df["日期"] >= end - pd.Timedelta(days=look_back_days))]
    header = f"## 卖方研报 Sell-side research on {s.canonical}, last {look_back_days} days to {as_of_date}\n"
    if df.empty:
        return header + "No reports published in this window."
    eps_cols = [c for c in df.columns if "盈利预测-收益" in c][:2]
    lines = ["| Date | Institution | Rating | Title | " + " | ".join(c.replace("-盈利预测-收益", " EPS") for c in eps_cols) + " |",
             "|---|---|---|---|" + "---:|" * len(eps_cols)]
    for _, r in df.head(limit).iterrows():
        eps = [_num(r.get(c)) for c in eps_cols]
        lines.append(f"| {r['日期']:%Y-%m-%d} | {r.get('机构')} | {r.get('东财评级')} | {str(r.get('报告名称'))[:40]} | "
                     + " | ".join(eps) + " |")
    ratings = df["东财评级"].value_counts()
    lines.append("\nRating distribution: " + ", ".join(f"{k} {v}" for k, v in ratings.items()))
    for c in eps_cols:
        vals = pd.to_numeric(df[c], errors="coerce").dropna()
        if len(vals):
            lines.append(f"Consensus {c.replace('-盈利预测-收益', '')} EPS: mean {vals.mean():.2f}, "
                         f"range {vals.min():.2f}-{vals.max():.2f} ({len(vals)} reports)")
    return header + "\n".join(lines)


def get_individual_fund_flow(symbol: str, as_of_date: str, sessions: int = 10) -> str:
    """Main-force net inflow by session. Eastmoney's quote servers often refuse
    non-mainland IPs; the call then reports the vendor unavailable."""
    s = parse_a_share(symbol)
    df = call_vendor("eastmoney fund flow", lambda: akshare().stock_individual_fund_flow(
        stock=s.code, market=s.exchange.lower()), attempts=1)
    df = df.copy()
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    df = df[df["日期"] <= pd.Timestamp(as_of_date)].tail(sessions)
    if df.empty:
        raise NoMarketDataError(symbol, canonical_symbol(symbol), "no fund-flow rows")
    lines = [f"## 主力资金流 Main-force net inflow for {s.canonical} (last {len(df)} sessions)",
             "| Date | Close | Chg % | Main net (万) | Main net % | Super-large net (万) | Large net (万) |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for _, r in df.iterrows():
        lines.append(f"| {r['日期']:%Y-%m-%d} | {_num(r.get('收盘价'))} | {_num(r.get('涨跌幅'))} "
                     f"| {_num((r.get('主力净流入-净额') or 0) / 1e4, '{:,.0f}')} | {_num(r.get('主力净流入-净占比'))} "
                     f"| {_num((r.get('超大单净流入-净额') or 0) / 1e4, '{:,.0f}')} "
                     f"| {_num((r.get('大单净流入-净额') or 0) / 1e4, '{:,.0f}')} |")
    return "\n".join(lines)
