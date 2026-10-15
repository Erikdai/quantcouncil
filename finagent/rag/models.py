"""Local ONNX embedding (bge-small-zh) and reranking (bge-reranker-v2-m3) models via fastembed."""

from __future__ import annotations

import asyncio
import threading
from functools import lru_cache

from langchain_core.embeddings import Embeddings

from finagent.config import get_settings

# BGE retrieval convention: short queries get an instruction prefix, passages do not.
BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："

_lock = threading.Lock()


@lru_cache(maxsize=1)
def _embedder():
    from fastembed import TextEmbedding  # noqa: PLC0415

    s = get_settings()
    with _lock:
        return TextEmbedding(model_name=s.embedding_model, cache_dir=s.model_cache_dir)


@lru_cache(maxsize=1)
def _reranker():
    s = get_settings()
    if not s.reranker_model:
        return None
    from fastembed.rerank.cross_encoder import TextCrossEncoder  # noqa: PLC0415

    with _lock:
        return TextCrossEncoder(model_name=s.reranker_model, cache_dir=s.model_cache_dir)


def embed_passages(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    if not texts:
        return []
    return [vec.tolist() for vec in _embedder().embed(texts, batch_size=batch_size)]


def embed_query(text: str) -> list[float]:
    prefixed = text if len(text) > 64 else BGE_QUERY_INSTRUCTION + text
    return next(iter(_embedder().embed([prefixed]))).tolist()


def rerank(query: str, passages: list[str]) -> list[float] | None:
    """Cross-encoder relevance scores, or None when reranking is disabled."""
    model = _reranker()
    if model is None or not passages:
        return None
    return [float(s) for s in model.rerank(query, passages, batch_size=16)]


class LocalEmbeddings(Embeddings):
    """LangChain adapter over the local model (used by the LangGraph store index)."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return embed_passages(list(texts))

    def embed_query(self, text: str) -> list[float]:
        return embed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(embed_passages, list(texts))

    async def aembed_query(self, text: str) -> list[float]:
        return await asyncio.to_thread(embed_query, text)
