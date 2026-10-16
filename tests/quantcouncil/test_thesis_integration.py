"""Real PostgreSQL transactions with model/network boundaries controlled separately."""

import uuid
from datetime import date

import httpx
import pytest

from quantcouncil.db import get_engine, session_scope
from quantcouncil.db.models import (
    ResearchJob,
    Thesis,
    ThesisExtraction,
    ThesisReview,
    ThesisVersion,
)
from quantcouncil.thesis_tracking.schemas import MeaningReview, ScopeReview
from quantcouncil.thesis_tracking.service import report_hash, run_review

pytestmark = pytest.mark.integration


@pytest.fixture
async def api(monkeypatch):
    from quantcouncil import llm_settings
    from quantcouncil.api.main import app
    from quantcouncil.api.routers import theses
    from quantcouncil.runtime import get_runtime

    async def no_queue(*args):
        pass

    monkeypatch.setattr(theses, "dispatch_review", no_queue)
    monkeypatch.setattr(llm_settings, "api_key", lambda *_: ("test-key", "test"))
    rt = await get_runtime().start(with_tools=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    await rt.stop()
    await get_engine().dispose()


async def seed_candidate():
    from quantcouncil import llm_settings
    from quantcouncil.thesis_tracking.schemas import Rule

    rule = Rule(template="threshold", period="annual", metric="operating_income", threshold="100")
    async with session_scope() as s:
        settings, _ = await llm_settings.resolve(s)
        source = ResearchJob(
            id=str(uuid.uuid4()),
            ticker="TEST",
            question="Test original financial claim",
            as_of=date(2025, 12, 31),
            language="en",
            status="completed",
            stage="completed",
            report={"answer": {"text": "Operating profit exceeds 100 USD million"}},
            sources=[],
            events=[],
            manifest=[],
            warnings=[],
            verification={"passed": True},
            model=settings.model_dump(),
        )
        s.add(source)
        await s.flush()
        candidate = {
            "original_text": "Operating profit exceeds 100 USD million",
            "origin_path": "answer",
            "statement": "Operating profit exceeds 100 USD million in each latest annual filing",
            "verification_class": "quantitative",
            "relationship": "new_hypothesis",
            "rule": rule.model_dump(mode="json"),
            "citations": [],
            "suggested_assumptions": ["Repeat in future annual disclosures"],
            "limitations": [],
            "extraction_errors": [],
        }
        extraction = ThesisExtraction(
            id=str(uuid.uuid4()),
            source_job_id=source.id,
            report_hash=report_hash(source),
            status="completed",
            candidates=[candidate],
            outputs=[],
            model=settings.model_dump(),
        )
        s.add(extraction)
        await s.flush()
        return extraction.id, candidate


async def create_verified(api):
    extraction_id, candidate = await seed_candidate()
    response = await api.post(
        "/api/theses",
        json={
            "extraction_id": extraction_id,
            "candidate_index": 0,
            "statement": candidate["statement"],
            "rule": candidate["rule"],
        },
    )
    assert response.status_code == 201, response.text
    ids = response.json()
    async with session_scope() as s:
        version = await s.get(ThesisVersion, ids["version_id"])
        version.meaning_review = {
            "rule_matches_statement": True,
            "relationship": "new_hypothesis",
            "issues": [],
        }
        baseline = await s.get(ThesisReview, ids["review_id"])
        baseline.status, baseline.result = (
            "completed",
            {"eligible": True, "judgment": "supported", "checks": [], "segment_roster": None},
        )
        fingerprint = version.contract_hash
    return ids, fingerprint, candidate


async def test_confirm_requires_baseline_explicit_new_hypothesis_and_exact_hash(api):
    ids, fingerprint, _ = await create_verified(api)
    path = f"/api/theses/{ids['thesis_id']}/confirm"
    body = {
        "version_id": ids["version_id"],
        "contract_hash": fingerprint,
        "acknowledge_baseline": True,
        "start_monitoring": False,
    }
    assert (await api.post(path, json=body)).status_code == 409
    assert (
        await api.post(path, json={**body, "contract_hash": "stale", "accept_reformulation": True})
    ).status_code == 409
    assert (await api.post(path, json={**body, "rule": {"threshold": 50}})).status_code == 422
    accepted = await api.post(path, json={**body, "accept_reformulation": True})
    assert accepted.status_code == 200, accepted.text
    assert (await api.post(path, json={**body, "accept_reformulation": True})).status_code == 409
    assert (
        await api.post(f"/api/theses/{ids['thesis_id']}/checks", json={"as_of": "2025-01-01"})
    ).status_code == 422


async def test_new_version_does_not_modify_active_rule_and_checks_are_idempotent(api):
    ids, fingerprint, candidate = await create_verified(api)
    root = f"/api/theses/{ids['thesis_id']}"
    confirm = {
        "version_id": ids["version_id"],
        "contract_hash": fingerprint,
        "acknowledge_baseline": True,
        "accept_reformulation": True,
        "start_monitoring": False,
    }
    assert (await api.post(root + "/confirm", json=confirm)).status_code == 200
    new_rule = {**candidate["rule"], "threshold": "200"}
    response = await api.post(
        root + "/versions",
        json={"statement": "Operating profit exceeds 200 USD million", "rule": new_rule},
    )
    assert response.status_code == 201, response.text
    detail = (await api.get(root)).json()
    assert detail["current_version"] == 1
    assert detail["versions"][0]["contract_hash"] == fingerprint
    assert detail["versions"][0]["rule"]["threshold"] == "100"
    assert detail["versions"][1]["rule"]["threshold"] == "200"
    # Pending v2 baseline cannot be returned as if it checked confirmed v1.
    assert (await api.post(root + "/checks", json={})).status_code == 409
    async with session_scope() as s:
        row = await s.get(ThesisReview, response.json()["review_id"])
        row.status = "failed"
    first = await api.post(root + "/checks", json={"as_of": "2025-12-31"})
    second = await api.post(root + "/checks", json={"as_of": "2025-12-31"})
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


async def test_scope_failure_preserves_last_judgment_and_does_not_change_rule(api, monkeypatch):
    from quantcouncil.thesis_tracking import service
    from quantcouncil.thesis_tracking.schemas import Rule
    from tests.quantcouncil.test_thesis_rules import fact, snapshot

    ids, fingerprint, _ = await create_verified(api)
    root = f"/api/theses/{ids['thesis_id']}"
    assert (
        await api.post(
            root + "/confirm",
            json={
                "version_id": ids["version_id"],
                "contract_hash": fingerprint,
                "acknowledge_baseline": True,
                "accept_reformulation": True,
                "start_monitoring": False,
            },
        )
    ).status_code == 200
    response = await api.post(root + "/checks", json={"as_of": "2025-12-31"})
    monkeypatch.setattr(
        service, "collect_snapshot", lambda *_: snapshot([fact("operating_income", 50)])
    )
    monkeypatch.setattr(service, "make_model", lambda *_: object())

    async def changed_scope(*args):
        return ScopeReview(
            comparable=False,
            issues=["Segment or accounting definition changed"],
            explanation="Human review required",
        )

    monkeypatch.setattr(service, "check_scope", changed_scope)
    await run_review(response.json()["id"])
    detail = (await api.get(root)).json()
    assert detail["judgment"] == "supported" and detail["data_health"] == "partial"
    assert detail["versions"][0]["contract_hash"] == fingerprint
    assert Rule.model_validate(detail["versions"][0]["rule"]).threshold == 100
    assert detail["reviews"][0]["status"] == "needs_review"


async def test_meaning_gate_blocks_proxy_even_if_user_tries_to_confirm(api, monkeypatch):
    from quantcouncil.thesis_tracking import service
    from tests.quantcouncil.test_thesis_rules import fact, snapshot

    ids, fingerprint, _ = await create_verified(api)
    async with session_scope() as s:
        row = await s.get(ThesisReview, ids["review_id"])
        row.status, row.result = "queued", None
    monkeypatch.setattr(
        service, "collect_snapshot", lambda *_: snapshot([fact("operating_income", 120)])
    )
    monkeypatch.setattr(service, "make_model", lambda *_: object())

    async def wrong_meaning(*args):
        return MeaningReview(
            rule_matches_statement=False,
            relationship="proxy",
            issues=["Group growth cannot prove AI commercialization"],
            assumptions=[],
            explanation="Wrong observable",
        )

    async def same_scope(*args):
        return ScopeReview(comparable=True, issues=[], explanation="Standard group metric")

    monkeypatch.setattr(service, "check_meaning", wrong_meaning)
    monkeypatch.setattr(service, "check_scope", same_scope)
    await run_review(ids["review_id"])
    response = await api.post(
        f"/api/theses/{ids['thesis_id']}/confirm",
        json={
            "version_id": ids["version_id"],
            "contract_hash": fingerprint,
            "acknowledge_baseline": True,
            "accept_reformulation": True,
            "start_monitoring": False,
        },
    )
    assert response.status_code == 409
    async with session_scope() as s:
        thesis = await s.get(Thesis, ids["thesis_id"])
        assert thesis.current_version == 0


async def test_stale_jobs_are_reaped_using_persisted_progress(api):
    from datetime import UTC, datetime, timedelta

    from quantcouncil.thesis_tracking.service import reap_stale

    extraction_id, _ = await seed_candidate()
    async with session_scope() as s:
        row = await s.get(ThesisExtraction, extraction_id)
        row.status = "running"
        row.updated_at = datetime.now(UTC) - timedelta(minutes=21)
    await reap_stale()
    async with session_scope() as s:
        row = await s.get(ThesisExtraction, extraction_id)
        assert row.status == "failed"
        assert "worker stopped" in row.error


async def test_unchanged_evidence_does_not_call_a_model_or_change_contract(api, monkeypatch):
    from quantcouncil.thesis_tracking import service
    from quantcouncil.thesis_tracking.rules import evaluate
    from quantcouncil.thesis_tracking.schemas import Rule
    from tests.quantcouncil.test_thesis_rules import fact, snapshot

    ids, fingerprint, candidate = await create_verified(api)
    root = f"/api/theses/{ids['thesis_id']}"
    evidence = snapshot([fact("operating_income", 120)])
    async with session_scope() as s:
        baseline = await s.get(ThesisReview, ids["review_id"])
        baseline.snapshot = evidence.model_dump(mode="json")
        baseline.result = evaluate(Rule.model_validate(candidate["rule"]), evidence)
    assert (
        await api.post(
            root + "/confirm",
            json={
                "version_id": ids["version_id"],
                "contract_hash": fingerprint,
                "acknowledge_baseline": True,
                "accept_reformulation": True,
                "start_monitoring": False,
            },
        )
    ).status_code == 200
    monkeypatch.setattr(service, "collect_snapshot", lambda *_: evidence)

    def unexpected(*args):
        raise AssertionError("Unchanged evidence must not incur model calls")

    monkeypatch.setattr(service, "make_model", unexpected)
    response = await api.post(root + "/checks", json={"as_of": "2025-12-31"})
    await run_review(response.json()["id"])
    detail = (await api.get(root)).json()
    assert detail["reviews"][0]["status"] == "unchanged"
    assert detail["reviews"][0]["outputs"] == []
    assert detail["versions"][0]["contract_hash"] == fingerprint
    assert detail["judgment"] == "supported"


async def test_scheduler_does_not_dispatch_a_pending_new_version_as_current(api, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from quantcouncil.thesis_tracking import service

    ids, fingerprint, candidate = await create_verified(api)
    root = f"/api/theses/{ids['thesis_id']}"
    assert (
        await api.post(
            root + "/confirm",
            json={
                "version_id": ids["version_id"],
                "contract_hash": fingerprint,
                "acknowledge_baseline": True,
                "accept_reformulation": True,
                "start_monitoring": False,
            },
        )
    ).status_code == 200
    assert (
        await api.post(
            root + "/versions",
            json={
                "statement": candidate["statement"],
                "rule": {**candidate["rule"], "threshold": "200"},
            },
        )
    ).status_code == 201
    async with session_scope() as s:
        thesis = await s.get(Thesis, ids["thesis_id"])
        thesis.lifecycle = "active"
        thesis.next_check_at = datetime.now(UTC) - timedelta(minutes=1)
    dispatched = []

    async def capture(review_id):
        dispatched.append(review_id)

    monkeypatch.setattr(service, "dispatch_review", capture)
    await service.poll_active()
    assert not dispatched


async def test_lifecycle_returns_refreshed_server_timestamp(api):
    ids, fingerprint, _ = await create_verified(api)
    root = f"/api/theses/{ids['thesis_id']}"
    assert (
        await api.post(
            root + "/confirm",
            json={
                "version_id": ids["version_id"],
                "contract_hash": fingerprint,
                "acknowledge_baseline": True,
                "accept_reformulation": True,
                "start_monitoring": False,
            },
        )
    ).status_code == 200
    for state in ("active", "paused", "archived"):
        result = await api.patch(root + "/lifecycle", json={"lifecycle": state})
        assert result.status_code == 200, result.text
        assert result.json()["lifecycle"] == state
        assert result.json()["updated_at"]
