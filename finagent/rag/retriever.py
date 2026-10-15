"""Hybrid retrieval: pgvector cosine + Postgres full-text (jieba), RRF fusion, cross-encoder rerank.

Modes: ``vector``, ``keyword``, ``hybrid``, ``hybrid_rerank``. All filter by ticker
and publication date.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text

from finagent.api.schemas import Citation
from finagent.db import session_scope
from finagent.rag import text as rag_text
from finagent.rag.models import embed_query, rerank

RRF_K = 60
MODES = ("vector", "keyword", "hybrid", "hybrid_rerank")


@dataclass
class Hit:
    chunk_id: int
    document_id: int
    content: str
    title: str
    url: str | None
    ticker: str | None
    published_at: date | None
    doc_type: str
    score: float


_FILTERS = """
    (CAST(:ticker AS text) IS NULL OR c.ticker = :ticker)
    AND (CAST(:as_of AS date) IS NULL OR c.published_at <= :as_of)
"""
_SELECT = """
    SELECT c.id AS chunk_id, c.document_id, c.content, d.title, d.url, c.ticker, c.published_at, d.doc_type
"""


async def _vector(session, query: str, ticker, as_of, limit: int) -> list[Hit]:
    vec = await asyncio.to_thread(embed_query, query)
    rows = (await session.execute(text(f"""
        {_SELECT}, 1 - (c.embedding <=> CAST(:vec AS vector)) AS score
        FROM chunks c JOIN documents d ON d.id = c.document_id
        WHERE {_FILTERS}
        ORDER BY c.embedding <=> CAST(:vec AS vector)
        LIMIT :limit"""), {"vec": str(vec), "ticker": ticker, "as_of": as_of, "limit": limit})).mappings().all()
    return [Hit(**r) for r in rows]


async def _keyword(session, query: str, ticker, as_of, limit: int) -> list[Hit]:
    q = rag_text.tsquery(query)
    if not q:
        return []
    rows = (await session.execute(text(f"""
        {_SELECT}, ts_rank_cd(c.tokens, to_tsquery('simple', :q)) AS score
        FROM chunks c JOIN documents d ON d.id = c.document_id
        WHERE c.tokens @@ to_tsquery('simple', :q) AND {_FILTERS}
        ORDER BY score DESC
        LIMIT :limit"""), {"q": q, "ticker": ticker, "as_of": as_of, "limit": limit})).mappings().all()
    return [Hit(**r) for r in rows]


def rrf(*ranked: list[Hit], k: int = RRF_K) -> list[Hit]:
    """Reciprocal Rank Fusion: score = Σ 1 / (k + rank). Robust to incomparable score scales."""
    fused: dict[int, Hit] = {}
    scores: dict[int, float] = {}
    for hits in ranked:
        for rank, hit in enumerate(hits, start=1):
            fused.setdefault(hit.chunk_id, hit)
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
    out = []
    for cid, hit in fused.items():
        out.append(Hit(**{**hit.__dict__, "score": scores[cid]}))
    return sorted(out, key=lambda h: h.score, reverse=True)


async def search(query: str, *, ticker: str | None = None, as_of: date | None = None, k: int = 8,
                 mode: str = "hybrid_rerank", candidates: int = 30) -> list[Hit]:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    async with session_scope() as session:
        if mode == "vector":
            return await _vector(session, query, ticker, as_of, k)
        if mode == "keyword":
            return await _keyword(session, query, ticker, as_of, k)
        vec_hits = await _vector(session, query, ticker, as_of, candidates)
        kw_hits = await _keyword(session, query, ticker, as_of, candidates)
    fused = rrf(vec_hits, kw_hits)
    if mode == "hybrid":
        return fused[:k]
    # Cross-encoder cost grows with candidates x length: rerank a short pool of
    # truncated passages (the title carries the document context).
    pool = fused[: max(k * 2, 12)]
    scores = await asyncio.to_thread(rerank, query, [f"{h.title}\n{h.content[:400]}" for h in pool])
    if scores is None:
        return pool[:k]
    reranked = [Hit(**{**h.__dict__, "score": s}) for h, s in zip(pool, scores, strict=True)]
    return sorted(reranked, key=lambda h: h.score, reverse=True)[:k]


def to_citation(hit: Hit, snippet_chars: int = 240) -> Citation:
    return Citation(chunk_id=hit.chunk_id, document_id=hit.document_id, title=hit.title, url=hit.url,
                    ticker=hit.ticker, published_at=hit.published_at, doc_type=hit.doc_type,
                    snippet=hit.content[:snippet_chars], score=round(float(hit.score), 4))


def format_hits(hits: list[Hit], max_chars: int = 600) -> str:
    """Numbered sources for an LLM prompt; the model cites them as [1], [2], ..."""
    if not hits:
        return "No matching passages in the research corpus (it may not be ingested for this ticker yet)."
    blocks = []
    for i, h in enumerate(hits, start=1):
        blocks.append(f"[{i}] {h.title} ({h.doc_type}, published {h.published_at})\n{h.content[:max_chars]}")
    return "\n\n".join(blocks)
