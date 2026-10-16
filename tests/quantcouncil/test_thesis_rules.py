from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from quantcouncil.deep_research.schemas import Evidence
from quantcouncil.thesis_tracking.rules import contract_hash, evaluate
from quantcouncil.thesis_tracking.schemas import Confirm, Rule, Snapshot


def fact(metric, value, year=2024, segment="consolidated", start=None, end=None):
    start, end = start or f"{year}-01-01", end or f"{year}-12-31"
    name = f"operating_income:{segment}" if metric == "operating_income" else metric
    return Evidence(
        id=f"{name}:{start}:{end}",
        kind="financial",
        title=name,
        content=f"{metric} {value} USD million",
        url="https://www.sec.gov/test",
        filed=f"{year + 1}-02-01",
        data={
            "cik": "1",
            "metric": name,
            "metric_name": metric,
            "segment": segment,
            "value": str(Decimal(str(value)) * 1000000),
            "unit": "USD",
            "frequency": "as_reported",
            "form": "10-K",
            "report_period": end,
            "start": start,
            "end": end,
        },
    )


def snapshot(sources):
    return Snapshot(
        ticker="TEST",
        as_of=date(2025, 12, 31),
        fetched_at="2025-12-31T12:00:00Z",
        fingerprint="test",
        manifest=[
            {
                "period": f"{y}-12-31",
                "form": "10-K",
                "accession": str(y),
                "sha256": str(y),
                "filed": f"{y + 1}-02-01",
            }
            for y in [2022, 2023, 2024]
        ],
        sources=sources,
        excerpts=[],
    )


def amazon():
    facts = []
    for segment, values in [
        ("consolidated", [36852, 68593]),
        ("AWS", [24631, 39834]),
        ("NA", [14877, 24967]),
        ("International", [-2656, 3792]),
    ]:
        facts.extend(
            fact("operating_income", v, year, segment)
            for year, v in zip([2023, 2024], values, strict=True)
        )
    return snapshot(facts)


def test_largest_is_not_majority_and_rule_is_never_mutated():
    rule = Rule(
        template="relative", period="annual", metric="operating_income", target_segment="AWS"
    )
    before = rule.model_dump_json()
    result = evaluate(rule, amazon())
    assert result["judgment"] == "supported"
    assert result["checks"][0]["contribution_pct"] == "47.90"
    assert rule.model_dump_json() == before
    assert evaluate(rule, amazon(), ["AWS", "NA"])["judgment"] == "insufficient"


def test_missing_peer_and_unreconciled_roster_block_a_ranking():
    rule = Rule(
        template="relative", period="annual", metric="operating_income", target_segment="AWS"
    )
    s = amazon()
    s.sources = [f for f in s.sources if f.data["segment"] != "International"]
    assert not evaluate(rule, s)["eligible"]
    s = amazon()
    s.sources = [
        f for f in s.sources if not (f.data["segment"] == "NA" and f.data["end"].startswith("2024"))
    ]
    assert evaluate(rule, s)["judgment"] == "insufficient"


def test_cash_shortfall_and_coverage_are_opposite_not_profit_proxies():
    s = snapshot(
        [
            fact(m, v)
            for m, v in [
                ("operating_cash_flow", 111482),
                ("capex", 12715),
                ("repurchases", 90711),
                ("dividends", 15421),
            ]
        ]
    )
    rule = Rule(
        template="coverage",
        period="annual",
        cash_outflows=["capex", "repurchases", "dividends"],
        coverage_expectation="shortfall",
    )
    r = evaluate(rule, s)
    assert r["judgment"] == "supported"
    assert r["checks"][0]["residual_usd"] == "-7365000000"
    assert (
        evaluate(rule.model_copy(update={"coverage_expectation": "covers"}), s)["judgment"]
        == "contradicted"
    )
    s.sources.pop()
    assert evaluate(rule, s)["judgment"] == "insufficient"


def test_trend_is_explicit_levels_not_percentage_from_a_negative_base():
    s = snapshot(
        [
            fact("operating_cash_flow", v, y)
            for y, v in [(2021, -100), (2022, -50), (2023, 0), (2024, 20)]
        ]
    )
    rule = Rule(template="trend", period="annual", observations=3)
    r = evaluate(rule, s)
    assert len(r["checks"]) == 3 and r["judgment"] == "supported"
    assert evaluate(rule, snapshot(s.sources[2:]))["judgment"] == "insufficient"


def test_threshold_cannot_use_rounded_display_margin():
    s = snapshot([fact("operating_income", "9.999"), fact("revenue", 100)])
    r = evaluate(
        Rule(
            template="threshold",
            period="annual",
            metric="operating_margin",
            operator="gte",
            threshold="10",
        ),
        s,
    )
    assert r["judgment"] == "contradicted"


def test_contract_covers_every_decision_field_and_original():
    rule = Rule(template="trend", period="annual").model_dump(mode="json")
    original = {"original_text": "A historical claim", "report_hash": "abc"}
    initial = contract_hash("A continuing claim", rule, "until_paused", original)
    for changed in [{**rule, "observations": 2}, {**rule, "period": "latest_reported"}]:
        assert contract_hash("A continuing claim", changed, "until_paused", original) != initial
    assert contract_hash("A different claim", rule, "until_paused", original) != initial


@pytest.mark.parametrize(
    "fields",
    [
        {
            "template": "relative",
            "metric": "operating_income",
            "target_segment": "AWS",
            "threshold": 50,
        },
        {"template": "trend", "observations": 0},
        {"template": "coverage", "cash_outflows": ["capex", "capex"]},
        {"template": "threshold", "threshold": None},
        {"template": "threshold", "threshold": "NaN"},
    ],
)
def test_invalid_or_extra_hidden_rules_fail_closed(fields):
    with pytest.raises(ValidationError):
        Rule(period="annual", **fields)
    with pytest.raises(ValidationError):
        Confirm(
            version_id="v", contract_hash="h", acknowledge_baseline=True, rule={"threshold": 50}
        )


@pytest.mark.asyncio
async def test_format_repair_retains_pydantic_validator_errors_without_serialization_crash():
    import json

    from langchain_core.messages import AIMessage

    from quantcouncil.deep_research.generation import structured

    class Model:
        model_name = "gpt-4.1"
        count = 0

        def with_structured_output(self, schema, **kwargs):
            return self

        async def ainvoke(self, messages):
            self.count += 1
            payload = {
                "template": "coverage",
                "period": "annual",
                "metric": "net_income" if self.count == 1 else "operating_cash_flow",
            }
            try:
                parsed = Rule.model_validate(payload)
                error = None
            except ValidationError as exc:
                parsed = None
                error = ValueError("Invalid schema")
                error.__cause__ = exc
            return {
                "raw": AIMessage(content=json.dumps(payload)),
                "parsed": parsed,
                "parsing_error": error,
            }

    recorded = []

    async def record(output):
        recorded.append(output)

    result = await structured(Model(), Rule, [], record)
    assert result.metric == "operating_cash_flow"
    assert len(recorded) == 2
    assert "Coverage uses operating cash flow" in recorded[0]["parsing_error"]
    json.dumps(recorded)  # All retained diagnostics must be JSON-safe for PostgreSQL.


def test_code_guard_catches_historical_to_future_even_when_model_says_direct():
    from quantcouncil.thesis_tracking.meaning import guard_meaning

    rule = Rule(template="coverage", period="annual")
    model = {
        "relationship": "direct",
        "rule_matches_statement": True,
        "issues": [],
        "assumptions": [],
        "explanation": "Model missed the temporal shift",
    }
    checked = guard_meaning(
        {"original_text": "2025财年经营现金流覆盖资本开支。"},
        "今后每次年报的经营现金流覆盖现金资产采购额。",
        rule,
        model,
    )
    assert checked["relationship"] == "new_hypothesis"
    assert checked["model_relationship"] == "direct" and model["relationship"] == "direct"
    assert checked["assumptions"]
    fixed = guard_meaning(
        {"original_text": "2025财年经营现金流覆盖资本开支。"},
        "2025财年经营现金流覆盖资本开支。",
        rule,
        model,
    )
    assert not fixed["rule_matches_statement"] and fixed["issues"]


def test_missing_latest_metric_cannot_reuse_an_older_period_as_fresh_support():
    s = snapshot([fact("operating_cash_flow", 100, 2023)])
    result = evaluate(Rule(template="threshold", period="annual", threshold="0"), s)
    assert result["judgment"] == "insufficient"
    assert "older-period substitution" in result["reason"]


def test_future_filed_fact_and_negative_expense_fail_closed():
    s = snapshot([fact("operating_cash_flow", 100), fact("capex", -10)])
    assert not evaluate(Rule(template="coverage", period="annual"), s)["eligible"]
    s.sources[1].data["value"] = "10000000"
    s.sources[0].filed = "2026-01-01"
    assert not evaluate(Rule(template="coverage", period="annual"), s)["eligible"]
