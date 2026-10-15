"""A-share profile, valuation and financial statements, point-in-time.

Statements carry their publication date (NOTICE_DATE), so a run dated D only sees
reports published by D. Valuation is a daily history and point-in-time as well.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

import pandas as pd

from tradingagents.dataflows.date_window import is_historical
from tradingagents.dataflows.errors import NoMarketDataError
from tradingagents.dataflows.vendors.cn.common import (
    akshare,
    cached,
    call_vendor,
    canonical_symbol,
    parse_a_share,
)

logger = logging.getLogger(__name__)

YI = 1e8  # statement figures are shown in units of CNY 100M

# Curated rows per statement: (column, label). The raw frames carry 200-300
# columns, mostly empty for a non-financial company; these are the lines an
# analyst reads first, and keep the tool output small enough for the prompt.
BALANCE_ROWS = [
    ("TOTAL_ASSETS", "总资产 Total assets"),
    ("TOTAL_CURRENT_ASSETS", "流动资产 Current assets"),
    ("MONETARYFUNDS", "货币资金 Cash"),
    ("ACCOUNTS_RECE", "应收账款 Receivables"),
    ("INVENTORY", "存货 Inventory"),
    ("FIXED_ASSET", "固定资产 Fixed assets"),
    ("GOODWILL", "商誉 Goodwill"),
    ("TOTAL_LIABILITIES", "总负债 Total liabilities"),
    ("TOTAL_CURRENT_LIAB", "流动负债 Current liabilities"),
    ("SHORT_LOAN", "短期借款 Short-term debt"),
    ("LONG_LOAN", "长期借款 Long-term debt"),
    ("CONTRACT_LIAB", "合同负债 Contract liabilities (prepaid orders)"),
    ("TOTAL_PARENT_EQUITY", "归母权益 Equity to parent"),
]
INCOME_ROWS = [
    ("TOTAL_OPERATE_INCOME", "营业总收入 Revenue"),
    ("OPERATE_COST", "营业成本 Cost of revenue"),
    ("SALE_EXPENSE", "销售费用 Selling expense"),
    ("MANAGE_EXPENSE", "管理费用 Admin expense"),
    ("RESEARCH_EXPENSE", "研发费用 R&D expense"),
    ("FINANCE_EXPENSE", "财务费用 Finance expense"),
    ("OPERATE_PROFIT", "营业利润 Operating profit"),
    ("TOTAL_PROFIT", "利润总额 Pre-tax profit"),
    ("NETPROFIT", "净利润 Net profit"),
    ("PARENT_NETPROFIT", "归母净利润 Net profit to parent"),
    ("DEDUCT_PARENT_NETPROFIT", "扣非归母净利润 Recurring net profit"),
]
CASHFLOW_ROWS = [
    ("NETCASH_OPERATE", "经营活动现金流净额 Operating cash flow"),
    ("CONSTRUCT_LONG_ASSET", "购建长期资产 Capex"),
    ("NETCASH_INVEST", "投资活动现金流净额 Investing cash flow"),
    ("ASSIGN_DIVIDEND_PORFIT", "分配股利及利息 Dividends & interest paid"),
    ("NETCASH_FINANCE", "筹资活动现金流净额 Financing cash flow"),
    ("CCE_ADD", "现金净增加额 Net change in cash"),
    ("END_CCE", "期末现金 Ending cash"),
]
_STATEMENTS = {
    "balance": ("stock_balance_sheet_by_report_em", BALANCE_ROWS, "Balance Sheet 资产负债表"),
    "income": ("stock_profit_sheet_by_report_em", INCOME_ROWS, "Income Statement 利润表"),
    "cashflow": ("stock_cash_flow_sheet_by_report_em", CASHFLOW_ROWS, "Cash Flow Statement 现金流量表"),
}


@cached(ttl=6 * 3600, namespace="statement")
def _statement_frame(kind: str, symbol: str) -> pd.DataFrame:
    fn_name = _STATEMENTS[kind][0]
    s = parse_a_share(symbol)
    df = call_vendor(f"eastmoney {kind}", lambda: getattr(akshare(), fn_name)(symbol=s.eastmoney), attempts=2)
    df = df.copy()
    df["NOTICE_DATE"] = pd.to_datetime(df["NOTICE_DATE"], errors="coerce")
    df["REPORT_DATE"] = pd.to_datetime(df["REPORT_DATE"], errors="coerce")
    return df.sort_values("REPORT_DATE", ascending=False).reset_index(drop=True)


def published_reports(kind: str, symbol: str, as_of: str | None, freq: str = "quarterly") -> pd.DataFrame:
    """Reports of ``kind`` published on or before ``as_of`` (all, when None), newest first."""
    df = _statement_frame(kind, canonical_symbol(symbol))
    if as_of:
        df = df[df["NOTICE_DATE"] <= pd.Timestamp(as_of)]
    if freq == "annual":
        df = df[df["REPORT_TYPE"] == "年报"]
    return df


def _fmt_yi(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value) / YI:,.2f}"


def _fmt_pct(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return f" ({float(value):+.1f}%)"


def _statement(kind: str, ticker: str, freq: str, curr_date: str | None) -> str:
    _, rows, title = _STATEMENTS[kind]
    canonical = canonical_symbol(ticker)
    periods = 3 if freq == "annual" else 4
    df = published_reports(kind, canonical, curr_date, freq).head(periods)
    if df.empty:
        raise NoMarketDataError(ticker, canonical, f"no {kind} statement published by {curr_date}")
    headers = [f"{r['REPORT_DATE_NAME']} (pub {r['NOTICE_DATE']:%Y-%m-%d})" for _, r in df.iterrows()]
    lines = [
        f"# {title} for {canonical} ({freq}, 亿元 CNY; YoY % in brackets)",
        f"# Point-in-time as of: {curr_date or 'latest'}; only reports published by then are shown",
        "",
        "| Item | " + " | ".join(headers) + " |",
        "|---|" + "---:|" * len(headers),
    ]
    for col, label in rows:
        if col not in df.columns or df[col].isna().all():
            continue
        cells = [_fmt_yi(r.get(col)) + _fmt_pct(r.get(f"{col}_YOY")) for _, r in df.iterrows()]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    if kind == "income" and "BASIC_EPS" in df.columns:
        lines.append("| 基本每股收益 Basic EPS (CNY) | " + " | ".join(
            "—" if pd.isna(r.get("BASIC_EPS")) else f"{float(r['BASIC_EPS']):.2f}" for _, r in df.iterrows()) + " |")
    lines += ["", "Interim figures (Q1/H1/Q3) are year-to-date cumulative, as A-share reports are filed."]
    return "\n".join(lines)


def get_cn_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
    return _statement("balance", ticker, freq, curr_date)


def get_cn_income_statement(ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
    return _statement("income", ticker, freq, curr_date)


def get_cn_cashflow(ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
    return _statement("cashflow", ticker, freq, curr_date)


# --- Profile and valuation ------------------------------------------------------

@cached(ttl=24 * 3600, namespace="profile")
def get_cn_profile(symbol: str) -> dict:
    """Company profile from cninfo: name, industry, listing date, business."""
    s = parse_a_share(symbol)
    df = call_vendor("cninfo profile", lambda: akshare().stock_profile_cninfo(symbol=s.code), attempts=2)
    if df is None or df.empty:
        raise NoMarketDataError(symbol, s.canonical, "no cninfo profile")
    row = df.iloc[0].to_dict()
    return {k: (None if pd.isna(v) else v) for k, v in row.items()}


@cached(ttl=3600, namespace="valuation")
def _valuation_frame(symbol: str) -> pd.DataFrame:
    s = parse_a_share(symbol)
    df = call_vendor("eastmoney valuation", lambda: akshare().stock_value_em(symbol=s.code), attempts=2)
    df = df.copy()
    df["数据日期"] = pd.to_datetime(df["数据日期"], errors="coerce")
    return df.dropna(subset=["数据日期"]).sort_values("数据日期").reset_index(drop=True)


def valuation_as_of(symbol: str, as_of: str) -> dict:
    """Latest daily valuation row on or before ``as_of`` plus the 3-year PE(TTM) percentile."""
    df = _valuation_frame(canonical_symbol(symbol))
    df = df[df["数据日期"] <= pd.Timestamp(as_of)]
    if df.empty:
        raise NoMarketDataError(symbol, canonical_symbol(symbol), f"no valuation history by {as_of}")
    last = df.iloc[-1]
    window = df[df["数据日期"] >= last["数据日期"] - pd.DateOffset(years=3)]
    pe = pd.to_numeric(window["PE(TTM)"], errors="coerce").dropna()
    pe = pe[pe > 0]
    pct = float((pe <= float(last["PE(TTM)"])).mean() * 100) if len(pe) and pd.notna(last["PE(TTM)"]) else None
    return {
        "date": last["数据日期"].strftime("%Y-%m-%d"),
        "close": last.get("当日收盘价"),
        "market_cap": last.get("总市值"),
        "float_cap": last.get("流通市值"),
        "pe_ttm": last.get("PE(TTM)"),
        "pe_static": last.get("PE(静)"),
        "pb": last.get("市净率"),
        "peg": last.get("PEG值"),
        "pcf": last.get("市现率"),
        "ps": last.get("市销率"),
        "pe_ttm_3y_percentile": pct,
    }


def _num(value, fmt="{:,.2f}") -> str:
    try:
        return "N/A" if value is None or pd.isna(value) else fmt.format(float(value))
    except (TypeError, ValueError):
        return str(value)


def get_cn_fundamentals(ticker: str, curr_date: str | None = None) -> str:
    """Profile, point-in-time valuation and the latest published headline figures."""
    canonical = canonical_symbol(ticker)
    curr_date = curr_date or date.today().isoformat()
    lines = [f"# Company Fundamentals for {canonical}", f"# Point-in-time as of: {curr_date}", ""]

    try:
        p = get_cn_profile(canonical)
        note = " (today's profile; names and industry rarely change)" if is_historical(curr_date) else ""
        lines += [f"## Profile{note}",
                  f"- Name: {p.get('公司名称')} ({p.get('A股简称')}), {p.get('英文名称') or ''}",
                  f"- Exchange: {p.get('所属市场')}; CSRC industry: {p.get('所属行业')}",
                  f"- Listed: {p.get('上市日期')}; Main business: {p.get('主营业务')}",
                  f"- Index membership: {str(p.get('入选指数') or '')[:200]}", ""]
    except Exception as exc:  # noqa: BLE001 — a profile outage should not hide valuation
        lines += [f"## Profile\nUnavailable ({type(exc).__name__}).", ""]

    try:
        v = valuation_as_of(canonical, curr_date)
        pct = v["pe_ttm_3y_percentile"]
        lines += [f"## Valuation on {v['date']} (daily history, point-in-time)",
                  f"- Close: {_num(v['close'])} CNY; Market cap: {_num((v['market_cap'] or 0) / YI)} 亿; "
                  f"Float cap: {_num((v['float_cap'] or 0) / YI)} 亿",
                  f"- PE(TTM): {_num(v['pe_ttm'])}; PE(static): {_num(v['pe_static'])}; PB: {_num(v['pb'])}; "
                  f"PEG: {_num(v['peg'])}; P/CF: {_num(v['pcf'])}; P/S: {_num(v['ps'])}",
                  f"- PE(TTM) 3-year percentile: {_num(pct, '{:.0f}%') if pct is not None else 'N/A'} "
                  "(share of the last 3 years' trading days with a PE at or below today's)", ""]
    except Exception as exc:  # noqa: BLE001
        lines += [f"## Valuation\nUnavailable ({type(exc).__name__}).", ""]

    try:
        inc = published_reports("income", canonical, curr_date).head(1)
        bal = published_reports("balance", canonical, curr_date).head(1)
        if not inc.empty:
            r = inc.iloc[0]
            lines += [f"## Latest published results: {r['REPORT_DATE_NAME']} (published {r['NOTICE_DATE']:%Y-%m-%d})",
                      f"- Revenue: {_fmt_yi(r.get('TOTAL_OPERATE_INCOME'))} 亿{_fmt_pct(r.get('TOTAL_OPERATE_INCOME_YOY'))}",
                      f"- Net profit to parent: {_fmt_yi(r.get('PARENT_NETPROFIT'))} 亿{_fmt_pct(r.get('PARENT_NETPROFIT_YOY'))}",
                      f"- Recurring net profit: {_fmt_yi(r.get('DEDUCT_PARENT_NETPROFIT'))} 亿"
                      f"{_fmt_pct(r.get('DEDUCT_PARENT_NETPROFIT_YOY'))}",
                      f"- Basic EPS: {_num(r.get('BASIC_EPS'))}"]
            if not bal.empty:
                b = bal.iloc[0]
                equity, assets, liab = b.get("TOTAL_PARENT_EQUITY"), b.get("TOTAL_ASSETS"), b.get("TOTAL_LIABILITIES")
                if pd.notna(equity) and equity and pd.notna(r.get("PARENT_NETPROFIT")):
                    lines.append(f"- ROE (period, not annualized): {float(r['PARENT_NETPROFIT']) / float(equity) * 100:.1f}%")
                if pd.notna(assets) and assets and pd.notna(liab):
                    lines.append(f"- Debt-to-assets: {float(liab) / float(assets) * 100:.1f}%")
            lines.append("")
    except Exception as exc:  # noqa: BLE001
        lines += [f"## Latest results\nUnavailable ({type(exc).__name__}).", ""]

    return "\n".join(lines)


# --- Shareholders (the A-share stand-in for insider transactions) ---------------

def _latest_disclosed_period(as_of: str) -> str:
    """Latest report period whose statutory disclosure deadline has passed by ``as_of``.

    Q1 by 30 Apr, H1 by 31 Aug, Q3 by 31 Oct, annual by 30 Apr of the next year.
    """
    d = datetime.strptime(as_of, "%Y-%m-%d").date()
    candidates = []
    for year in (d.year, d.year - 1):
        candidates += [
            (date(year, 3, 31), date(year, 4, 30)),
            (date(year, 6, 30), date(year, 8, 31)),
            (date(year, 9, 30), date(year, 10, 31)),
            (date(year, 12, 31), date(year + 1, 4, 30)),
        ]
    period = max(p for p, deadline in candidates if deadline <= d)
    return period.strftime("%Y%m%d")


@cached(ttl=24 * 3600, namespace="top10float")
def _top10_float(prefixed: str, period: str) -> pd.DataFrame:
    return call_vendor("eastmoney top10 float holders",
                       lambda: akshare().stock_gdfx_free_top_10_em(symbol=prefixed, date=period), attempts=2)


def get_cn_insider_transactions(ticker: str, as_of: str | None = None) -> str:
    """Top-10 float shareholders and their changes for the latest disclosed period.

    A-share insiders file holding changes through exchange announcements rather
    than a Form 4 feed; the top-10 float holder table (with holding changes) is the
    point-in-time view every report discloses.
    """
    s = parse_a_share(ticker)
    as_of = as_of or date.today().isoformat()
    period = _latest_disclosed_period(as_of)
    df = _top10_float(s.prefixed, period)
    if df is None or df.empty:
        raise NoMarketDataError(ticker, s.canonical, f"no top-10 float holder table for {period}")
    lines = [f"# Top-10 float shareholders of {s.canonical}, period {period} (disclosed by {as_of})", "",
             "| Rank | Holder | Type | Shares | % of float | Change |", "|---:|---|---|---:|---:|---|"]
    for _, r in df.iterrows():
        change = r.get("增减")
        ratio = r.get("变动比率")
        if pd.notna(ratio):
            change = f"{change} ({float(ratio):+.2f}%)"
        lines.append(f"| {r.get('名次')} | {r.get('股东名称')} | {r.get('股东性质')} | {_num(r.get('持股数'), '{:,.0f}')} "
                     f"| {_num(r.get('占总流通股本持股比例'))}% | {change} |")
    return "\n".join(lines)
