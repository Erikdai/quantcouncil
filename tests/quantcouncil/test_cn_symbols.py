import pytest

from tradingagents.dataflows.vendors.cn import (
    canonical_symbol,
    is_a_share,
    is_cn_index,
    limit_prices,
    parse_a_share,
    price_limit_pct,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("raw,canonical", [
    ("600519", "600519.SS"), ("600519.SH", "600519.SS"), ("600519.ss", "600519.SS"), ("SH600519", "600519.SS"),
    ("sh.600519", "600519.SS"), ("000001", "000001.SZ"), ("sz000001", "000001.SZ"), ("300750", "300750.SZ"),
    ("688981", "688981.SS"), ("430047", "430047.BJ"), ("920002", "920002.BJ"), ("510300", "510300.SS"),
    ("159915", "159915.SZ"),
])
def test_every_spelling_resolves_to_one_canonical_symbol(raw, canonical):
    assert canonical_symbol(raw) == canonical


def test_an_explicit_suffix_beats_the_code_range():
    # 000001 is Ping An Bank on Shenzhen, but 000001.SS is the Shanghai Composite.
    assert canonical_symbol("000001") == "000001.SZ"
    assert canonical_symbol("000001.SS") == "000001.SS"
    assert is_cn_index("000001.SS") and not is_cn_index("000001.SZ")


@pytest.mark.parametrize("raw", ["NVDA", "AAPL", "0700.HK", "60051", "6005199", "", "BTC-USD"])
def test_non_a_shares_are_rejected(raw):
    assert not is_a_share(raw)


def test_vendor_forms():
    s = parse_a_share("600519")
    assert (s.prefixed, s.baostock, s.eastmoney) == ("sh600519", "sh.600519", "SH600519")


@pytest.mark.parametrize("code,st,pct,board", [
    ("600519", False, 0.10, "main"), ("600519", True, 0.05, "main"), ("300750", False, 0.20, "chinext"),
    ("300750", True, 0.20, "chinext"), ("688981", False, 0.20, "star"), ("430047", False, 0.30, "bse"),
])
def test_price_limits_by_board(code, st, pct, board):
    assert price_limit_pct(code, st) == pct
    assert parse_a_share(code).board == board


def test_limit_prices_round_to_the_fen():
    assert limit_prices("600519", 1286.0) == (1414.6, 1157.4)
    assert limit_prices("000001", 10.05) == (11.06, 9.05)  # 11.055 rounds half up
    assert limit_prices("600000", 3.33, is_st=True) == (3.5, 3.16)
