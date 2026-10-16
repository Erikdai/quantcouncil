"""Extract -> assess -> explicitly confirm -> review; no editable confirmed contracts."""

import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from quantcouncil import llm_settings
from quantcouncil.api.deps import RateLimited, SessionDep
from quantcouncil.db.models import (
    ResearchJob,
    Thesis,
    ThesisExtraction,
    ThesisReview,
    ThesisVersion,
)
from quantcouncil.thesis_tracking.rules import contract_hash
from quantcouncil.thesis_tracking.schemas import (
    CheckCreate,
    Confirm,
    ExtractionCreate,
    LifecycleChange,
    RevisionCreate,
    VersionCreate,
)
from quantcouncil.thesis_tracking.service import ACTIVE, dispatch_review, queue_review, report_hash

router = APIRouter(prefix="/api/theses", tags=["investment hypotheses"])


def public(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


async def get_thesis(session, thesis_id, lock=False):
    thesis = await session.get(Thesis, thesis_id, with_for_update=lock)
    if thesis is None:
        raise HTTPException(404, "Thesis not found")
    return thesis


@router.post("/extractions", status_code=201, dependencies=[RateLimited])
async def create_extraction(body: ExtractionCreate, session: SessionDep):
    from quantcouncil.worker.tasks import extract_theses  # noqa: PLC0415

    source = await session.get(ResearchJob, body.source_job_id)
    if source is None:
        raise HTTPException(404, "Source research not found")
    if source.status in ACTIVE or not source.report:
        raise HTTPException(409, "Wait for a terminal research report before extracting hypotheses")
    settings, overrides = await llm_settings.resolve(session)
    if not overrides.get("api_key"):
        raise HTTPException(422, "Configure a model API key first")
    row = ThesisExtraction(
        id=str(uuid.uuid4()),
        source_job_id=source.id,
        status="queued",
        report_hash=report_hash(source),
        candidates=[],
        outputs=[],
        model=settings.model_dump(),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    try:
        await extract_theses.kiq(row.id)
    except Exception as exc:
        row.status, row.error = "failed", f"Worker queue unavailable: {type(exc).__name__}"
        await session.commit()
    await session.refresh(row)
    return public(row)


@router.get("/extractions/{extraction_id}")
async def extraction(extraction_id: str, session: SessionDep):
    row = await session.get(ThesisExtraction, extraction_id)
    if row is None:
        raise HTTPException(404, "Extraction not found")
    return public(row)


@router.get("")
async def list_theses(session: SessionDep):
    rows = (
        (await session.execute(select(Thesis).order_by(Thesis.created_at.desc()).limit(100)))
        .scalars()
        .all()
    )
    result = []
    for row in rows:
        latest = (
            await session.execute(
                select(ThesisVersion)
                .where(ThesisVersion.thesis_id == row.id)
                .order_by(ThesisVersion.number.desc())
                .limit(1)
            )
        ).scalar_one()
        result.append(
            {
                **public(row),
                "statement": latest.statement,
                "latest_version": latest.number,
                "data_health": health(row),
            }
        )
    return result


def health(thesis):
    if (
        thesis.lifecycle == "active"
        and thesis.last_checked_at
        and datetime.now(UTC) - thesis.last_checked_at > timedelta(hours=48)
    ):
        return "stale"
    return thesis.data_health


async def add_version(session, thesis, statement, rule, horizon, origin, model):
    active = (
        await session.execute(
            select(ThesisReview.id).where(
                ThesisReview.thesis_id == thesis.id, ThesisReview.status.in_(ACTIVE)
            )
        )
    ).scalar_one_or_none()
    if active:
        raise HTTPException(409, "An existing review must finish before creating another version")
    number = (
        await session.execute(
            select(func.max(ThesisVersion.number)).where(ThesisVersion.thesis_id == thesis.id)
        )
    ).scalar_one() or 0
    rule_data = rule.model_dump(mode="json") if rule else None
    version = ThesisVersion(
        id=str(uuid.uuid4()),
        thesis_id=thesis.id,
        number=number + 1,
        statement=statement,
        horizon=horizon,
        rule=rule_data,
        origin=origin,
        contract_hash=contract_hash(statement, rule_data, horizon, origin),
        model=model,
    )
    session.add(version)
    await session.flush()
    review = await queue_review(
        session, thesis, version, date.fromisoformat(origin["source_cutoff"]), "baseline"
    )
    version.baseline_review_id = review.id
    await session.commit()
    await dispatch_review(review.id)
    return {"thesis_id": thesis.id, "version_id": version.id, "review_id": review.id}


@router.post("", status_code=201, dependencies=[RateLimited])
async def create_thesis(body: VersionCreate, session: SessionDep):
    extraction = await session.get(ThesisExtraction, body.extraction_id)
    if extraction is None or extraction.status != "completed":
        raise HTTPException(409, "A completed extraction is required")
    if body.candidate_index >= len(extraction.candidates):
        raise HTTPException(422, "Candidate not found")
    source = await session.get(ResearchJob, extraction.source_job_id)
    if report_hash(source) != extraction.report_hash:
        raise HTTPException(409, "Original report changed; extract again")
    c = extraction.candidates[body.candidate_index]
    origin = {
        **c,
        "extraction_id": extraction.id,
        "source_job_id": source.id,
        "source_cutoff": str(source.as_of),
        "report_hash": extraction.report_hash,
        "source_checks_passed": bool((source.verification or {}).get("passed")),
    }
    thesis = Thesis(
        id=str(uuid.uuid4()),
        ticker=source.ticker,
        lifecycle="draft",
        current_version=0,
        data_health="unknown",
    )
    session.add(thesis)
    await session.flush()
    return await add_version(
        session, thesis, body.statement, body.rule, body.horizon, origin, extraction.model
    )


@router.get("/{thesis_id}")
async def detail(thesis_id: str, session: SessionDep):
    thesis = await get_thesis(session, thesis_id)
    versions = (
        (
            await session.execute(
                select(ThesisVersion)
                .where(ThesisVersion.thesis_id == thesis.id)
                .order_by(ThesisVersion.number)
            )
        )
        .scalars()
        .all()
    )
    reviews = (
        (
            await session.execute(
                select(ThesisReview)
                .where(ThesisReview.thesis_id == thesis.id)
                .order_by(ThesisReview.created_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    return {
        **public(thesis),
        "data_health": health(thesis),
        "versions": [public(v) for v in versions],
        "reviews": [public(r) for r in reviews],
    }


@router.post("/{thesis_id}/versions", status_code=201, dependencies=[RateLimited])
async def revise(thesis_id: str, body: RevisionCreate, session: SessionDep):
    thesis = await get_thesis(session, thesis_id, True)
    first = (
        await session.execute(
            select(ThesisVersion)
            .where(ThesisVersion.thesis_id == thesis.id)
            .order_by(ThesisVersion.number)
            .limit(1)
        )
    ).scalar_one()
    settings, overrides = await llm_settings.resolve(session)
    if not overrides.get("api_key"):
        raise HTTPException(422, "Configure a model API key first")
    return await add_version(
        session,
        thesis,
        body.statement,
        body.rule,
        body.horizon,
        first.origin,
        settings.model_dump(),
    )


@router.post("/{thesis_id}/confirm")
async def confirm(thesis_id: str, body: Confirm, session: SessionDep):
    thesis = await get_thesis(session, thesis_id, True)
    version = await session.get(ThesisVersion, body.version_id, with_for_update=True)
    if version is None or version.thesis_id != thesis.id:
        raise HTTPException(404, "Version not found")
    latest = (
        await session.execute(
            select(func.max(ThesisVersion.number)).where(ThesisVersion.thesis_id == thesis.id)
        )
    ).scalar_one()
    if version.number != latest or version.confirmed_at is not None:
        raise HTTPException(409, "Only the latest unconfirmed version can be confirmed")
    if (
        body.contract_hash != version.contract_hash
        or contract_hash(version.statement, version.rule, version.horizon, version.origin)
        != version.contract_hash
    ):
        raise HTTPException(409, "Contract changed; reload and inspect the exact version")
    baseline = await session.get(ThesisReview, version.baseline_review_id)
    if (
        baseline is None
        or baseline.status != "completed"
        or not (baseline.result or {}).get("eligible")
        or not version.rule
    ):
        raise HTTPException(
            409,
            "Trackability and baseline verification must pass; user approval cannot bypass them",
        )
    if version.rule.get("template") == "relative" and not baseline.result.get(
        "scope_review", {}
    ).get("citations_verified"):
        raise HTTPException(409, "An exhaustive, source-cited segment-roster check is required")
    meaning = version.meaning_review or {}
    if not meaning.get("rule_matches_statement") or meaning.get("issues"):
        raise HTTPException(409, "Rule meaning requires correction")
    changed = version.statement != version.origin[
        "statement"
    ] or version.rule != version.origin.get("rule")
    reformulated = (
        meaning.get("relationship") != "direct"
        or changed
        or bool(version.origin.get("suggested_assumptions"))
        or bool(meaning.get("assumptions"))
    )
    if reformulated and not body.accept_reformulation:
        raise HTTPException(
            409,
            "Explicitly accept this new/narrowed hypothesis; it does not validate the broader original claim",
        )
    version.confirmed_at = datetime.now(UTC)
    version.confirmation = body.model_dump()
    thesis.current_version, thesis.lifecycle = (
        version.number,
        "active" if body.start_monitoring else "paused",
    )
    thesis.judgment, thesis.last_review_id = baseline.result["judgment"], baseline.id
    thesis.data_health = "pending" if body.start_monitoring else "historical"
    thesis.next_check_at = datetime.now(UTC)
    review = (
        await queue_review(session, thesis, version, date.today(), "manual")
        if body.start_monitoring
        else None
    )
    if review and review.version_id != version.id:
        raise HTTPException(409, "An older-version review is active; confirm after it finishes")
    await session.commit()
    if review:
        await dispatch_review(review.id)
    return {
        "thesis_id": thesis.id,
        "version": version.number,
        "lifecycle": thesis.lifecycle,
        "review_id": review.id if review else None,
    }


@router.post("/{thesis_id}/checks", status_code=201, dependencies=[RateLimited])
async def check(thesis_id: str, body: CheckCreate, session: SessionDep):
    thesis = await get_thesis(session, thesis_id, True)
    version = (
        await session.execute(
            select(ThesisVersion).where(
                ThesisVersion.thesis_id == thesis.id, ThesisVersion.number == thesis.current_version
            )
        )
    ).scalar_one_or_none()
    if version is None or version.confirmed_at is None:
        raise HTTPException(409, "Confirm a verified rule before subsequent checks")
    as_of = body.as_of or date.today()
    if as_of > date.today() or as_of < date.fromisoformat(version.origin["source_cutoff"]):
        raise HTTPException(422, "Review cutoff must be between baseline and today")
    row = await queue_review(session, thesis, version, as_of, "manual")
    if row.version_id != version.id:
        raise HTTPException(409, "Another version is being reviewed; wait for it to finish")
    await session.commit()
    await dispatch_review(row.id)
    return public(row)


@router.patch("/{thesis_id}/lifecycle")
async def lifecycle(thesis_id: str, body: LifecycleChange, session: SessionDep):
    thesis = await get_thesis(session, thesis_id, True)
    if body.lifecycle == "active" and thesis.current_version == 0:
        raise HTTPException(409, "An unconfirmed hypothesis cannot be monitored")
    thesis.lifecycle = body.lifecycle
    thesis.next_check_at = datetime.now(UTC)
    if body.lifecycle == "active":
        thesis.data_health = "pending"
    await session.commit()
    await session.refresh(thesis)
    return public(thesis)


@router.post("/{thesis_id}/reviews/{review_id}/read")
async def mark_read(thesis_id: str, review_id: str, session: SessionDep):
    row = await session.get(ThesisReview, review_id)
    if row is None or row.thesis_id != thesis_id:
        raise HTTPException(404, "Review not found")
    row.unread = False
    await session.commit()
    return {"read": True}
