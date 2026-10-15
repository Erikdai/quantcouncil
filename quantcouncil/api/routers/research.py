"""Research assistant (streaming chat with RAG + MCP tools + skills), corpus search and ingestion."""

from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sse_starlette.sse import EventSourceResponse

from quantcouncil.api.deps import RateLimited, SessionDep
from quantcouncil.api.schemas import ChatRequest, DocumentOut, IngestRequest, SearchOut, SkillOut
from quantcouncil.db.models import Chunk, Document
from quantcouncil.markets import resolve_instrument
from quantcouncil.rag.retriever import MODES, search, to_citation
from quantcouncil.skills import get_skill, list_skills

router = APIRouter(tags=["research"])


def _ticker(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return resolve_instrument(raw).ticker
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/api/research/chat", dependencies=[RateLimited])
async def chat(body: ChatRequest):
    from quantcouncil.agents.research_agent import stream_chat  # noqa: PLC0415

    if not body.messages or body.messages[-1].role != "user":
        raise HTTPException(422, "the last message must be the user's")

    async def events():
        async for type_, data in stream_chat(body.messages, ticker=_ticker(body.ticker), thread_id=body.thread_id):
            yield {"event": type_, "data": json.dumps(data, ensure_ascii=False, default=str)}

    return EventSourceResponse(events(), ping=15, headers={"X-Accel-Buffering": "no"})


@router.get("/api/research/search", response_model=SearchOut)
async def search_docs(q: str = Query(..., min_length=1), ticker: str | None = None, k: int = Query(8, le=30),
                      mode: str = "hybrid_rerank", as_of: date | None = None) -> SearchOut:
    if mode not in MODES:
        raise HTTPException(422, f"mode must be one of {MODES}")
    hits = await search(q, ticker=_ticker(ticker), as_of=as_of, k=k, mode=mode)
    return SearchOut(query=q, mode=mode, results=[to_citation(h) for h in hits])


@router.post("/api/research/ingest", status_code=202)
async def ingest(body: IngestRequest) -> dict:
    from quantcouncil.worker.tasks import ingest_documents  # noqa: PLC0415

    ticker = _ticker(body.ticker)
    task = await ingest_documents.kiq(ticker, list(body.kinds), body.since.isoformat() if body.since else None,
                                      body.limit)
    return {"task_id": task.task_id}


@router.get("/api/research/documents", response_model=list[DocumentOut])
async def documents(session: SessionDep, ticker: str | None = None,
                    limit: int = Query(100, le=500)) -> list[DocumentOut]:
    q = (select(Document, func.count(Chunk.id)).outerjoin(Chunk, Chunk.document_id == Document.id)
         .group_by(Document.id).order_by(Document.published_at.desc().nullslast()).limit(limit))
    if ticker:
        q = q.where(Document.ticker == _ticker(ticker))
    rows = (await session.execute(q)).all()
    return [DocumentOut(id=d.id, ticker=d.ticker, title=d.title, doc_type=d.doc_type, url=d.url,
                        published_at=d.published_at, chunks=n, created_at=d.created_at) for d, n in rows]


@router.get("/api/skills", response_model=list[SkillOut], tags=["skills"])
async def skills() -> list[SkillOut]:
    return [SkillOut(name=s.name, description=s.description) for s in list_skills()]


@router.get("/api/skills/{name}", response_model=SkillOut, tags=["skills"])
async def skill(name: str) -> SkillOut:
    s = get_skill(name)
    if s is None:
        raise HTTPException(404, "skill not found")
    return SkillOut(name=s.name, description=s.description, body=s.body)
