"""A-share company news (Eastmoney) and market telegraph (Cailian Press).

Both feeds serve only recent items, so an unobserved window is reported as a
coverage gap rather than as "no news".
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from tradingagents.dataflows.date_window import coverage_gap, in_window
from tradingagents.dataflows.vendors.cn.common import (
    akshare,
    cached,
    call_vendor,
    canonical_symbol,
    parse_a_share,
)

_CN_TZ = "Asia/Shanghai"


def _to_dt(value) -> datetime | None:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize(_CN_TZ)
    return ts.to_pydatetime()


@cached(ttl=600, namespace="news-em")
def _company_news(code: str) -> pd.DataFrame:
    return call_vendor("eastmoney stock news", lambda: akshare().stock_news_em(symbol=code))


def company_news_items(ticker: str, start_date: str, end_date: str) -> tuple[list[dict], list]:
    """News items for the ticker inside the window, and every item's timestamp."""
    s = parse_a_share(ticker)
    df = _company_news(s.code)
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    items, stamps = [], []
    for _, r in df.iterrows():
        published = _to_dt(r.get("发布时间"))
        stamps.append(published)
        if not in_window(published, start, end):
            continue
        items.append({
            "title": str(r.get("新闻标题") or "").strip(),
            "content": str(r.get("新闻内容") or "").strip(),
            "source": r.get("文章来源"),
            "published": published.strftime("%Y-%m-%d %H:%M") if published else "undated",
            "url": r.get("新闻链接"),
        })
    return items, stamps


def get_cn_news(ticker: str, start_date: str, end_date: str) -> str:
    canonical = canonical_symbol(ticker)
    items, stamps = company_news_items(canonical, start_date, end_date)
    gap = coverage_gap(stamps, start_date, end_date, "Eastmoney company news", f"news about {canonical}")
    header = f"## {canonical} news (Eastmoney 东方财富), {start_date} to {end_date}\n"
    if not items:
        return header + (gap or f"No company news for {canonical} in this window.")
    body = "\n\n".join(
        f"### {it['title']} ({it['source']}, {it['published']})\n{it['content'][:400]}\nLink: {it['url']}"
        for it in items)
    return header + ("\n" + gap + "\n\n" if gap else "\n") + body


@cached(ttl=300, namespace="cls-telegraph")
def _telegraph() -> pd.DataFrame:
    return call_vendor("cls telegraph", lambda: akshare().stock_info_global_cls(symbol="全部"))


def get_cn_global_news(curr_date: str, look_back_days: int | None = None, limit: int | None = None) -> str:
    """Market-moving headlines from the Cailian Press telegraph."""
    look_back_days = 3 if look_back_days is None else look_back_days
    limit = 20 if limit is None else limit
    end = datetime.strptime(curr_date, "%Y-%m-%d")
    start = end - timedelta(days=look_back_days)
    df = _telegraph()
    items, stamps = [], []
    for _, r in df.iterrows():
        published = _to_dt(f"{r.get('发布日期')} {r.get('发布时间')}")
        stamps.append(published)
        if in_window(published, start, end):
            title = str(r.get("标题") or "").strip()
            content = str(r.get("内容") or "").strip()
            items.append(f"- [{published:%Y-%m-%d %H:%M}] {title + ': ' if title else ''}{content[:300]}")
    start_s = start.strftime("%Y-%m-%d")
    gap = coverage_gap(stamps, start_s, curr_date, "Cailian Press telegraph", "market news")
    header = f"## China market telegraph (财联社), {start_s} to {curr_date}\n"
    if not items:
        return header + (gap or "No telegraph items in this window.")
    return header + ("\n" + gap + "\n\n" if gap else "\n") + "\n".join(items[:limit])
