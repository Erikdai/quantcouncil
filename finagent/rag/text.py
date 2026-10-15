"""Chinese text for retrieval: PDF cleaning, chunking, and jieba tokens for Postgres full-text search."""

from __future__ import annotations

import logging
import re
from functools import lru_cache

logger = logging.getLogger(__name__)

_SENTENCE_END = re.compile(r"(?<=[。！？；!?;])|\n{2,}")
_WS = re.compile(r"[ \t　\xa0]+")
_PAGE_NOISE = re.compile(r"^\s*(第\s*\d+\s*页|\d+\s*/\s*\d+|-\s*\d+\s*-)\s*$", re.M)
_TOKEN_OK = re.compile(r"[\w一-鿿]")
_STOP = frozenset(["的", "了", "和", "与", "及", "或", "等", "在", "是", "为", "对", "中", "上", "下", "之", "其", "将", "已", "于", "由", "从", "以", "而", "并", "也", "被", "把", "这", "那", "有", "无", "不", "个", "年", "月", "日"])


_LEADERS = re.compile(r"[.·…_\-]{4,}")                 # table-of-contents dot leaders
_LAYOUT_TAGS = re.compile(r"\[Table_\w+\]|\$\$\w+\$\$")  # broker report template tags


def clean(text: str) -> str:
    """Normalize PDF-extracted text: drop page-number lines, layout tags and dot leaders,
    join broken lines inside sentences."""
    text = _PAGE_NOISE.sub("", text or "")
    text = _LAYOUT_TAGS.sub(" ", text)
    text = _LEADERS.sub(" ", text)
    text = _WS.sub(" ", text)
    # pypdf breaks lines at the visual line end; rejoin a line that does not end a sentence.
    text = re.sub(r"(?<=[一-鿿，、：\w])\n(?=[一-鿿\w])", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk(text: str, size: int = 500, overlap: int = 80) -> list[str]:
    """Sentence-aligned chunks of about ``size`` characters with ``overlap`` carried over."""
    sentences = [s.strip() for s in _SENTENCE_END.split(text) if s and s.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > size:  # a sentence longer than a chunk (tables) is cut hard
            head, sentence = sentence[:size], sentence[size - overlap:]
            if current:
                chunks.append(current)
                current = ""
            chunks.append(head)
        if len(current) + len(sentence) + 1 > size and current:
            chunks.append(current)
            current = current[-overlap:] if overlap else ""
        current = f"{current}{sentence}" if not current or current.endswith(("\n", "。")) else f"{current} {sentence}"
    if current.strip():
        chunks.append(current)
    return [c.strip() for c in chunks if len(c.strip()) >= 20 and informative(c)]


def informative(passage: str) -> bool:
    """False for passages that are mostly numbers (financial-table dumps), which
    embed poorly and crowd out prose in retrieval."""
    body = re.sub(r"\s", "", passage)
    if not body:
        return False
    cjk = sum(1 for ch in body if "一" <= ch <= "鿿")
    digits = sum(1 for ch in body if ch.isdigit() or ch in ".,%-+()")
    return cjk / len(body) >= 0.25 or digits / len(body) < 0.5


@lru_cache(maxsize=1)
def _jieba():
    import jieba  # noqa: PLC0415

    jieba.setLogLevel(logging.WARNING)
    for word in ("归母净利润", "扣非净利润", "营业总收入", "经营活动现金流", "毛利率", "净利率", "市盈率",
                 "市净率", "龙虎榜", "融资融券", "涨停板", "跌停板", "北向资金", "主力资金", "股权激励",
                 "回购", "减持", "增持", "分红", "派息", "业绩预告", "业绩快报", "年度报告", "半年度报告"):
        jieba.add_word(word)
    return jieba


def tokens(text: str) -> list[str]:
    """jieba search-mode tokens without punctuation and stop words, lower-cased."""
    out = []
    for tok in _jieba().cut_for_search(text or ""):
        tok = tok.strip().lower()
        if tok and _TOKEN_OK.search(tok) and tok not in _STOP:
            out.append(tok)
    return out


def tsquery(text: str) -> str | None:
    """An OR-query for ``to_tsquery('simple', ...)``, or None when nothing is searchable."""
    seen = []
    for tok in tokens(text):
        safe = re.sub(r"[^\w一-鿿]", "", tok)
        if safe and safe not in seen:
            seen.append(safe)
    return " | ".join(seen) if seen else None
