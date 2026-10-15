"""Evaluation CLI.

    python -m finagent.evals rag    --dataset PATH [--k 5]         retrieval ablation table
    python -m finagent.evals judge  RUN_ID [RUN_ID ...]            LLM-as-judge on finished runs
    python -m finagent.evals judge  --recent 10                     ... on the latest completed runs
"""

from __future__ import annotations

import argparse
import asyncio

import finagent  # noqa: F401  (event-loop policy on Windows)


async def _rag(args) -> None:
    from finagent.evals.rag_eval import benchmark, load_dataset, render  # noqa: PLC0415

    dataset = load_dataset(args.dataset)
    results = await benchmark(dataset, k=args.k)
    print(f"Retrieval benchmark: {len(dataset)} queries, k={args.k}\n")
    print(render(results, args.k))


async def _judge(args) -> None:
    from sqlalchemy import select  # noqa: PLC0415

    from finagent.db import session_scope  # noqa: PLC0415
    from finagent.db.models import Run  # noqa: PLC0415
    from finagent.evals.judge import evaluate_and_store  # noqa: PLC0415

    run_ids = list(args.run_ids)
    if args.recent:
        async with session_scope() as s:
            rows = (await s.execute(select(Run.id).where(Run.final_decision.is_not(None))
                                    .order_by(Run.created_at.desc()).limit(args.recent))).scalars().all()
            run_ids += rows
    print("| run | mean | grounding | consistency | balance | risk | action | passed |")
    print("|---|---:|---:|---:|---:|---:|---:|---|")
    for run_id in run_ids:
        r = await evaluate_and_store(run_id)
        s = r.scores
        print(f"| {run_id[:8]} | {s['judge_mean']:.2f} | {s['grounding']:.0f} | {s['consistency']:.0f} | "
              f"{s['balance']:.0f} | {s['risk_awareness']:.0f} | {s['actionability']:.0f} | {r.passed} |")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="finagent-eval")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_rag = sub.add_parser("rag", help="retrieval ablation")
    p_rag.add_argument("--dataset", required=True,
                       help='JSONL of {"query", "ticker", "must_contain": [...]}')
    p_rag.add_argument("--k", type=int, default=5)
    p_judge = sub.add_parser("judge", help="LLM-as-judge on runs")
    p_judge.add_argument("run_ids", nargs="*")
    p_judge.add_argument("--recent", type=int, default=0)
    args = parser.parse_args(argv)
    asyncio.run(_rag(args) if args.cmd == "rag" else _judge(args))


if __name__ == "__main__":
    main()
