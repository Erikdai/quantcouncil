"""Durable extraction/baseline/check jobs and a rule-invariant publication gate."""

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from quantcouncil import llm_settings
from quantcouncil.db import session_scope
from quantcouncil.db.models import (
    ResearchJob,
    Thesis,
    ThesisExtraction,
    ThesisReview,
    ThesisVersion,
)
from quantcouncil.thesis_tracking.ai import (
    check_meaning,
    check_scope,
    extract,
    make_model,
    validate_candidates,
)
from quantcouncil.thesis_tracking.data import collect_snapshot
from quantcouncil.thesis_tracking.meaning import guard_meaning
from quantcouncil.thesis_tracking.rules import EVALUATOR_VERSION, contract_hash, evaluate
from quantcouncil.thesis_tracking.schemas import Rule

ACTIVE = ("queued", "running")


def report_hash(job):
    return hashlib.sha256(
        json.dumps(
            {"report": job.report, "sources": job.sources}, sort_keys=True, ensure_ascii=False
        ).encode()
    ).hexdigest()


async def run_extraction(extraction_id: str):
    async with session_scope() as s:
        job = await s.get(ThesisExtraction, extraction_id, with_for_update=True)
        if job is None or job.status != "queued":
            return
        job.status = "running"
        source = await s.get(ResearchJob, job.source_job_id)
        if source is None or report_hash(source) != job.report_hash:
            job.status, job.error = "failed", "Source report changed; create a new extraction"
            return
        ticker, report, sources = source.ticker, source.report, source.sources
        _, overrides = await llm_settings.resolve(s, job.model)
    outputs = []

    async def record(output):
        outputs.append(output)
        async with session_scope() as s:
            row = await s.get(ThesisExtraction, extraction_id)
            row.outputs, row.updated_at = list(outputs), datetime.now(UTC)

    try:
        async with asyncio.timeout(600):
            batch = await extract(make_model(ticker, overrides, "quick"), report, sources, record)
        candidates = list(validate_candidates(batch, report, sources))
        async with session_scope() as s:
            row = await s.get(ThesisExtraction, extraction_id)
            row.candidates, row.status, row.updated_at = candidates, "completed", datetime.now(UTC)
    except Exception as exc:
        async with session_scope() as s:
            row = await s.get(ThesisExtraction, extraction_id)
            row.status, row.error = "failed", f"{type(exc).__name__}: {str(exc)[:400]}"
            row.updated_at = datetime.now(UTC)


async def run_review(review_id: str):
    async with session_scope() as s:
        row = await s.get(ThesisReview, review_id, with_for_update=True)
        if row is None or row.status != "queued":
            return
        row.status, row.updated_at = "running", datetime.now(UTC)
        version = await s.get(ThesisVersion, row.version_id)
        thesis = await s.get(Thesis, row.thesis_id)
        # Deep-copy the contract outside the ORM transaction. No model output is
        # ever assigned to these fields after creation.
        frozen = {
            "statement": version.statement,
            "rule": version.rule,
            "horizon": version.horizon,
            "origin": version.origin,
            "contract_hash": version.contract_hash,
        }
        ticker, kind, as_of = thesis.ticker, row.kind, row.as_of
        _, overrides = await llm_settings.resolve(s, version.model)
        baseline = (
            await s.get(ThesisReview, version.baseline_review_id)
            if version.baseline_review_id
            else None
        )
        baseline_snapshot = baseline.snapshot if baseline and baseline.snapshot else {}
        locked_roster = (baseline.result or {}).get("segment_roster") if baseline else None
        previous = (
            await s.get(ThesisReview, thesis.last_review_id) if thesis.last_review_id else None
        )
        previous_snapshot = (
            previous.snapshot if previous and previous.snapshot else baseline_snapshot
        )
        previous_result = (
            previous.result
            if previous and previous.result
            else (baseline.result if baseline else None)
        )
    outputs = []

    async def record(output):
        outputs.append(output)
        async with session_scope() as s:
            row = await s.get(ThesisReview, review_id)
            if row.status != "running":
                raise ValueError("Review no longer active")
            row.outputs, row.updated_at = list(outputs), datetime.now(UTC)

    try:
        async with asyncio.timeout(900):
            if (
                contract_hash(
                    frozen["statement"], frozen["rule"], frozen["horizon"], frozen["origin"]
                )
                != frozen["contract_hash"]
            ):
                raise ValueError("Stored contract hash mismatch; automatic review blocked")
            errors = list(frozen["origin"].get("extraction_errors", []))
            snapshot = None
            meaning = None
            if frozen["rule"] is None:
                result = {
                    "judgment": "insufficient",
                    "eligible": False,
                    "reason": "No executable quantitative hypothesis; save only",
                    "checks": [],
                    "sources": [],
                    "segment_roster": None,
                    "evaluator_version": EVALUATOR_VERSION,
                }
            else:
                rule = Rule.model_validate(frozen["rule"])
                snapshot = await asyncio.to_thread(collect_snapshot, ticker, as_of)
                result = evaluate(rule, snapshot, locked_roster if kind != "baseline" else None)
                async with session_scope() as s:
                    row = await s.get(ThesisReview, review_id)
                    row.snapshot, row.result, row.updated_at = (
                        snapshot.model_dump(mode="json"),
                        result,
                        datetime.now(UTC),
                    )
                # Unchanged discoveries do not call a model or strengthen evidence.
                old_files = {
                    (f["accession"], f["sha256"]) for f in previous_snapshot.get("manifest", [])
                }
                new_files = {(f["accession"], f["sha256"]) for f in snapshot.manifest}
                unchanged = (
                    kind != "baseline"
                    and result["eligible"]
                    and previous_result
                    and previous_result.get("eligible")
                    and new_files <= old_files
                    and result["checks"] == previous_result.get("checks")
                )
                if unchanged:
                    await finish_review(review_id, frozen, snapshot, result, None, [], "unchanged")
                    return
                model = make_model(ticker, overrides)
                if kind == "baseline":
                    meaning = (
                        await check_meaning(
                            model,
                            frozen["origin"],
                            frozen["statement"],
                            frozen["rule"],
                            frozen["horizon"],
                            result,
                            record,
                        )
                    ).model_dump()
                    meaning = guard_meaning(frozen["origin"], frozen["statement"], rule, meaning)
                    errors.extend(meaning["issues"])
                    if not meaning["rule_matches_statement"]:
                        errors.append("The executable rule does not match the proposed statement")
                if result["eligible"] and not errors:
                    scope = (
                        await check_scope(
                            model,
                            frozen,
                            baseline_snapshot,
                            snapshot.model_dump(mode="json"),
                            result,
                            record,
                        )
                    ).model_dump()
                    by_id = {e.id: e.model_dump(mode="json") for e in snapshot.excerpts}
                    by_id.update({e["id"]: e for e in result["sources"]})
                    valid_cites = bool(scope["citations"]) and all(
                        c["source_id"] in by_id
                        and " ".join(c["quote"].split())
                        in " ".join(by_id[c["source_id"]]["content"].split())
                        for c in scope["citations"]
                    )
                    financial = [e for e in result["sources"] if e["kind"] == "financial"]
                    latest_filed = max((e["filed"] for e in financial), default=None)
                    latest_accessions = {
                        e["accession"] for e in financial if e["filed"] == latest_filed
                    }
                    roster_proven = rule.template != "relative" or (
                        scope["roster_complete"]
                        and any(
                            by_id.get(c["source_id"])
                            and by_id[c["source_id"]]["kind"] == "filing"
                            and by_id[c["source_id"]].get("accession") in latest_accessions
                            for c in scope["citations"]
                        )
                    )
                    scope["citations_verified"] = valid_cites and roster_proven
                    if not scope["citations_verified"]:
                        errors.append(
                            "Scope review lacks exact source evidence or an exhaustive segment-roster citation"
                        )
                    result["scope_review"] = scope
                    included = {e["id"] for e in result["sources"]}
                    for cite in scope["citations"]:
                        key = cite["source_id"]
                        if key in by_id and key not in included:
                            result["sources"].append(by_id[key])
                            included.add(key)
                    if not scope["comparable"] or scope["issues"]:
                        errors.extend(
                            scope["issues"] or ["Evidence scope/completeness requires human review"]
                        )
            result["eligibility_errors"] = errors
            result["eligible"] = result["eligible"] and not errors
            await finish_review(
                review_id,
                frozen,
                snapshot,
                result,
                meaning,
                errors,
                "needs_review" if errors else "completed",
            )
    except Exception as exc:
        async with session_scope() as s:
            identity = await s.get(ThesisReview, review_id)
            thesis = await s.get(Thesis, identity.thesis_id, with_for_update=True)
            row = await s.get(ThesisReview, review_id, with_for_update=True, populate_existing=True)
            if row.status == "running":
                row.status, row.error, row.updated_at = (
                    "failed",
                    f"{type(exc).__name__}: {str(exc)[:400]}",
                    datetime.now(UTC),
                )
                version = await s.get(ThesisVersion, row.version_id)
                if thesis.current_version == version.number:
                    thesis.data_health = "failed"
                    thesis.next_check_at = datetime.now(UTC) + timedelta(days=1)


async def finish_review(review_id, frozen, snapshot, result, meaning, errors, status):
    async with session_scope() as s:
        identity = await s.get(ThesisReview, review_id)
        thesis = await s.get(Thesis, identity.thesis_id, with_for_update=True)
        version = await s.get(ThesisVersion, identity.version_id, with_for_update=True)
        row = await s.get(ThesisReview, review_id, with_for_update=True, populate_existing=True)
        if row.status != "running" or version.contract_hash != frozen["contract_hash"]:
            raise ValueError("Review or contract changed during evaluation")
        if (
            contract_hash(version.statement, version.rule, version.horizon, version.origin)
            != version.contract_hash
        ):
            raise ValueError("Confirmed rule was modified outside version creation")
        row.status, row.result, row.updated_at = status, result, datetime.now(UTC)
        if snapshot:
            row.snapshot = snapshot.model_dump(mode="json")
            key = hashlib.sha256(
                f"{version.contract_hash}:{snapshot.fingerprint}".encode()
            ).hexdigest()
            existing = (
                await s.execute(
                    select(ThesisReview.id).where(
                        ThesisReview.version_id == version.id,
                        ThesisReview.evidence_key == key,
                        ThesisReview.id != row.id,
                    )
                )
            ).scalar_one_or_none()
            if existing is None and status != "unchanged":
                row.evidence_key = key
        if row.kind == "baseline":
            if version.confirmed_at is not None:
                raise ValueError("Confirmed baselines are immutable")
            version.meaning_review, version.baseline_review_id = meaning, row.id
            return
        previous = (
            await s.get(ThesisReview, thesis.last_review_id) if thesis.last_review_id else None
        )
        if thesis.current_version != version.number or (previous and row.as_of < previous.as_of):
            return  # A late old-version or historical replay never replaces current state.
        thesis.last_checked_at = datetime.now(UTC)
        thesis.next_check_at = datetime.now(UTC) + timedelta(days=1)
        if errors or not result["eligible"]:
            thesis.data_health = "partial"
            return
        if status != "unchanged":
            row.unread = (
                thesis.lifecycle == "active"
                and row.as_of == date.today()
                and thesis.judgment != result["judgment"]
            )
            thesis.last_review_id, thesis.judgment = row.id, result["judgment"]
        thesis.data_health = "fresh" if row.as_of == date.today() else "historical"


async def queue_review(session, thesis, version, as_of, kind):
    active = (
        await session.execute(
            select(ThesisReview).where(
                ThesisReview.thesis_id == thesis.id, ThesisReview.status.in_(ACTIVE)
            )
        )
    ).scalar_one_or_none()
    if active:
        return active
    row = ThesisReview(
        id=str(uuid.uuid4()),
        thesis_id=thesis.id,
        version_id=version.id,
        kind=kind,
        status="queued",
        as_of=as_of,
        outputs=[],
        unread=False,
    )
    session.add(row)
    await session.flush()
    return row


async def dispatch_review(review_id):
    from quantcouncil.worker.tasks import review_thesis  # noqa: PLC0415

    try:
        await review_thesis.kiq(review_id)
    except Exception as exc:
        async with session_scope() as s:
            row = await s.get(ThesisReview, review_id)
            row.status, row.error = "failed", f"Worker queue unavailable: {type(exc).__name__}"
            thesis = await s.get(Thesis, row.thesis_id)
            version = await s.get(ThesisVersion, row.version_id)
            if thesis.current_version == version.number:
                thesis.data_health = "failed"


async def poll_active():
    ids = []
    async with session_scope() as s:
        rows = (
            (
                await s.execute(
                    select(Thesis)
                    .where(Thesis.lifecycle == "active", Thesis.next_check_at <= datetime.now(UTC))
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for thesis in rows:
            version = (
                await s.execute(
                    select(ThesisVersion).where(
                        ThesisVersion.thesis_id == thesis.id,
                        ThesisVersion.number == thesis.current_version,
                    )
                )
            ).scalar_one()
            row = await queue_review(s, thesis, version, date.today(), "scheduled")
            if row.version_id != version.id or row.status != "queued":
                continue
            ids.append(row.id)
            thesis.next_check_at = datetime.now(UTC) + timedelta(days=1)
    for review_id in ids:
        await dispatch_review(review_id)
    return ids


async def reap_stale():
    async with session_scope() as s:
        cutoff = datetime.now(UTC) - timedelta(minutes=20)
        # Match API/publication lock order: thesis first, then review.
        stale = select(ThesisReview.thesis_id).where(
            ThesisReview.status.in_(ACTIVE), ThesisReview.updated_at < cutoff
        )
        theses = (
            (
                await s.execute(
                    select(Thesis).where(Thesis.id.in_(stale)).with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for thesis in theses:
            rows = (
                (
                    await s.execute(
                        select(ThesisReview)
                        .where(
                            ThesisReview.thesis_id == thesis.id,
                            ThesisReview.status.in_(ACTIVE),
                            ThesisReview.updated_at < cutoff,
                        )
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                row.status, row.error = (
                    "failed",
                    "No progress for 20 minutes; retry without changing the confirmed rule",
                )
                version = await s.get(ThesisVersion, row.version_id)
                if thesis.current_version == version.number:
                    thesis.data_health = "failed"
        extractions = (
            (
                await s.execute(
                    select(ThesisExtraction).where(
                        ThesisExtraction.status.in_(ACTIVE), ThesisExtraction.updated_at < cutoff
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in extractions:
            row.status, row.error = "failed", "Extraction worker stopped; start a new extraction"
