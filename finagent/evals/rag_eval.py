"""Retrieval benchmark: hit@k and MRR per retrieval mode on a labelled query set."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from finagent.rag.retriever import MODES, search


@dataclass
class ModeResult:
    mode: str
    hit_at_1: float
    hit_at_k: float
    mrr: float
    latency_ms: float


def load_dataset(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _rank(hits, must_contain: list[str]) -> int | None:
    for i, h in enumerate(hits, start=1):
        text = f"{h.title}\n{h.content}"
        if all(s in text for s in must_contain):
            return i
    return None


async def benchmark(dataset: list[dict], k: int = 5, modes=MODES) -> list[ModeResult]:
    results = []
    for mode in modes:
        ranks, elapsed = [], 0.0
        for item in dataset:
            t = time.perf_counter()
            hits = await search(item["query"], ticker=item.get("ticker"), k=k, mode=mode)
            elapsed += time.perf_counter() - t
            ranks.append(_rank(hits, item["must_contain"]))
        n = len(dataset) or 1
        results.append(ModeResult(
            mode=mode,
            hit_at_1=sum(1 for r in ranks if r == 1) / n,
            hit_at_k=sum(1 for r in ranks if r) / n,
            mrr=sum(1 / r for r in ranks if r) / n,
            latency_ms=elapsed / n * 1000,
        ))
    return results


def render(results: list[ModeResult], k: int) -> str:
    lines = [f"| mode | hit@1 | hit@{k} | MRR | latency (ms) |", "|---|---:|---:|---:|---:|"]
    lines += [f"| {r.mode} | {r.hit_at_1:.2f} | {r.hit_at_k:.2f} | {r.mrr:.3f} | {r.latency_ms:.0f} |" for r in results]
    return "\n".join(lines)
