"""Ingest exchange announcements (cninfo) and broker reports (Eastmoney): PDF to indexed chunks."""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache

import httpx
from sqlalchemy import func, select

from quantcouncil.config import get_settings
from quantcouncil.db import session_scope
from quantcouncil.db.models import Chunk, Document
from quantcouncil.rag import text as rag_text
from quantcouncil.rag.models import embed_passages

logger = logging.getLogger(__name__)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QuantCouncil/0.1 research"}
MAX_PAGES = 40           # annual reports run to 200+ pages; the first 40 hold the MD&A summary
MAX_CHUNKS_PER_DOC = 200


@dataclass
class SourceDoc:
    ticker: str
    title: str
    doc_type: str      # announcement | research
    source: str        # cninfo | eastmoney
    url: str
    published_at: date
    meta: dict


@lru_cache(maxsize=1)
def _cninfo_org_ids() -> dict[str, str]:
    """code -> cninfo orgId (needed by the announcement query)."""
    out: dict[str, str] = {}
    for url in ("http://www.cninfo.com.cn/new/data/szse_stock.json", "http://www.cninfo.com.cn/new/data/bj_stock.json"):
        try:
            data = httpx.get(url, headers=UA, timeout=30).json()
            out.update({s["code"]: s["orgId"] for s in data.get("stockList", [])})
        except Exception as exc:  # noqa: BLE001
            logger.warning("cninfo org id list %s failed: %s", url, exc)
    return out


def list_announcements(ticker: str, since: date, until: date, limit: int) -> list[SourceDoc]:
    from tradingagents.dataflows.vendors.cn import parse_a_share  # noqa: PLC0415

    s = parse_a_share(ticker)
    org_id = _cninfo_org_ids().get(s.code) or f"gs{s.exchange.lower()}0{s.code}"
    column = {"SH": "sse", "SZ": "szse", "BJ": "bj"}[s.exchange]
    resp = httpx.post("http://www.cninfo.com.cn/new/hisAnnouncement/query", headers=UA, timeout=30, data={
        "stock": f"{s.code},{org_id}", "tabName": "fulltext", "pageSize": min(limit * 2, 50), "pageNum": 1,
        "column": column, "category": "", "plate": "", "seDate": f"{since:%Y-%m-%d}~{until:%Y-%m-%d}",
        "searchkey": "", "secid": "", "sortName": "", "sortType": "", "isHLtitle": "true"})
    resp.raise_for_status()
    docs = []
    for a in resp.json().get("announcements") or []:
        if not a.get("adjunctUrl", "").lower().endswith(".pdf"):
            continue
        title = str(a.get("announcementTitle", "")).replace("<em>", "").replace("</em>", "")
        # Skip boilerplate filings that carry no analysis value.
        if any(k in title for k in ("英文版", "摘要", "法律意见书", "董事会议事规则", "独立董事述职")):
            continue
        published = datetime.fromtimestamp(a["announcementTime"] / 1000).date()
        docs.append(SourceDoc(ticker=s.canonical, title=title, doc_type="announcement", source="cninfo",
                              url="http://static.cninfo.com.cn/" + a["adjunctUrl"], published_at=published,
                              meta={"announcement_id": a.get("announcementId")}))
    return docs[:limit]


def list_research(ticker: str, since: date, until: date, limit: int) -> list[SourceDoc]:
    from tradingagents.dataflows.vendors.cn import parse_a_share  # noqa: PLC0415
    from tradingagents.dataflows.vendors.cn.capital import research_reports_frame  # noqa: PLC0415

    s = parse_a_share(ticker)
    df = research_reports_frame(s.code)
    df = df[(df["日期"].dt.date >= since) & (df["日期"].dt.date <= until)].head(limit)
    return [SourceDoc(ticker=s.canonical, title=str(r["报告名称"]), doc_type="research", source="eastmoney",
                      url=str(r["报告PDF链接"]), published_at=r["日期"].date(),
                      meta={"institution": r.get("机构"), "rating": r.get("东财评级")})
            for _, r in df.iterrows() if str(r.get("报告PDF链接", "")).startswith("http")]


def pdf_text(content: bytes) -> str:
    from pypdf import PdfReader  # noqa: PLC0415

    reader = PdfReader(io.BytesIO(content))
    pages = []
    for page in reader.pages[:MAX_PAGES]:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 — one unreadable page should not lose the document
            continue
    return rag_text.clean("\n\n".join(pages))


async def _download(client: httpx.AsyncClient, url: str) -> bytes:
    resp = await client.get(url, headers=UA, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


async def ingest_documents(docs: list[SourceDoc]) -> dict:
    """Download, parse, chunk, embed and store; skips documents already indexed (by URL)."""
    settings = get_settings()
    stats = {"seen": len(docs), "indexed": 0, "skipped": 0, "failed": 0, "chunks": 0}
    async with httpx.AsyncClient() as client:
        for doc in docs:
            digest = hashlib.sha256(doc.url.encode()).hexdigest()
            async with session_scope() as session:
                exists = (await session.execute(select(Document.id).where(Document.content_hash == digest))
                          ).scalar_one_or_none()
            if exists:
                stats["skipped"] += 1
                continue
            try:
                raw = await _download(client, doc.url)
                body = await asyncio.to_thread(pdf_text, raw)
                pieces = rag_text.chunk(body, settings.chunk_size, settings.chunk_overlap)[:MAX_CHUNKS_PER_DOC]
                if not pieces:
                    raise ValueError("no extractable text (scanned PDF?)")
                # The title goes into every chunk's embedding text: it carries the
                # document type and period that body chunks often lack.
                vectors = await asyncio.to_thread(embed_passages, [f"{doc.title}\n{p}" for p in pieces])
            except Exception as exc:  # noqa: BLE001
                logger.warning("ingest failed for %s (%s): %s", doc.title, doc.url, exc)
                stats["failed"] += 1
                continue
            async with session_scope() as session:
                row = Document(ticker=doc.ticker, title=doc.title, doc_type=doc.doc_type, source=doc.source,
                               url=doc.url, published_at=doc.published_at, content_hash=digest,
                               meta={**doc.meta, "pages_read": MAX_PAGES, "chars": len(body)})
                session.add(row)
                await session.flush()
                for i, (piece, vec) in enumerate(zip(pieces, vectors, strict=True)):
                    seg = " ".join(rag_text.tokens(f"{doc.title} {piece}"))
                    session.add(Chunk(document_id=row.id, ticker=doc.ticker, published_at=doc.published_at,
                                      chunk_index=i, content=piece, embedding=vec,
                                      tokens=func.to_tsvector("simple", seg)))
            stats["indexed"] += 1
            stats["chunks"] += len(pieces)
    return stats


async def ingest_ticker(ticker: str, kinds: list[str], since: date | None = None, limit: int = 10,
                        until: date | None = None) -> dict:
    until = until or date.today()
    since = since or (until - timedelta(days=365))
    docs: list[SourceDoc] = []
    if "announcement" in kinds:
        docs += await asyncio.to_thread(list_announcements, ticker, since, until, limit)
    if "research" in kinds:
        docs += await asyncio.to_thread(list_research, ticker, since, until, limit)
    stats = await ingest_documents(docs)
    logger.info("ingested %s: %s", ticker, stats)
    return stats
