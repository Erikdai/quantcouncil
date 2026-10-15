from datetime import date

import pytest

from quantcouncil.rag import text
from quantcouncil.rag.retriever import Hit, rrf

pytestmark = pytest.mark.unit


def test_clean_removes_pdf_noise():
    raw = "目录 ........................ 12\n[Table_Title] 公司点评\n第 3 页\n营业收入同比增长\n12.5%。"
    out = text.clean(raw)
    assert "....." not in out and "[Table_" not in out and "第 3 页" not in out
    assert "营业收入同比增长12.5%。" in out  # broken line rejoined


def test_chunks_are_bounded_and_overlap():
    body = "".join(f"第{i}句讲的是公司第{i}项业务的收入情况。" for i in range(80))
    chunks = text.chunk(body, size=200, overlap=40)
    assert len(chunks) > 5
    assert all(len(c) <= 260 for c in chunks)
    assert chunks[0][-20:] in chunks[1]  # carried-over context


def test_number_dumps_are_not_informative():
    assert not text.informative("2024 2025 2026E 1,234.5 2,345.6 3,456.7 12.3% 13.4% 14.5% 0.12 0.13")
    assert text.informative("公司2026年上半年实现营业收入910.94亿元，同比增长9.2%。")


def test_jieba_tokens_and_or_query():
    toks = text.tokens("贵州茅台2026年半年度报告的归母净利润")
    assert "归母净利润" in toks and "的" not in toks
    q = text.tsquery("归母净利润 同比")
    assert q is not None and " | " in q


def _hit(cid, score=0.0):
    return Hit(chunk_id=cid, document_id=1, content="", title="t", url=None, ticker="600519.SS",
               published_at=date(2026, 1, 1), doc_type="research", score=score)


def test_rrf_rewards_agreement_between_rankers():
    vector = [_hit(1), _hit(2), _hit(3)]
    keyword = [_hit(3), _hit(4), _hit(1)]
    fused = [h.chunk_id for h in rrf(vector, keyword)]
    assert fused[:2] == [1, 3]  # in both lists, ranked high
    assert set(fused) == {1, 2, 3, 4}
