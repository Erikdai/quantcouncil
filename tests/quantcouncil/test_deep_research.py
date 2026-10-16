"""Evidence boundaries: no future filings, no hidden content, no invented quotes/calculations."""

from datetime import date

import pytest

from quantcouncil.deep_research.engine import validate_report
from quantcouncil.deep_research.finance import calculate, financial_series
from quantcouncil.deep_research.schemas import Evidence, ResearchCreate, ResearchReport
from quantcouncil.deep_research.sec import (
    Filing,
    FilingCorpus,
    filing_text,
    filing_url,
    list_filings,
)


def fact(metric="revenue", end="2025-06-30", start="2024-07-01", value="100000000", **extra):
    return Evidence(
        id=metric + end,
        kind="financial",
        title=metric,
        url="https://www.sec.gov/test",
        filed="2025-07-30",
        content="Revenue as filed: 100 USD million",
        data={
            "metric": metric,
            "end": end,
            "start": start,
            "unit": "USD",
            "value": value,
            "frequency": "annual",
            "cik": "0000000001",
            **extra,
        },
    )


def test_calculations_have_inspectable_inputs_and_exact_results():
    later = fact(value="150000000")
    earlier = fact(end="2024-06-30", start="2023-07-01")
    growth = calculate(later, earlier, "growth_pct")
    assert growth.data["result"] == "50.00"
    assert growth.inputs == [later.id, earlier.id]
    ocf = fact(metric="operating_cash_flow", value="200000000")
    capex = fact(metric="capex", value="80000000")
    assert calculate(ocf, capex, "difference").data["result"] == "120.00"


def test_reject_mixed_reporting_periods_and_zero_baselines():
    with pytest.raises(ValueError, match="identical reporting periods"):
        calculate(fact(), fact(start="2025-04-01"), "ratio_pct")
    with pytest.raises(ValueError, match="zero/negative"):
        calculate(fact(), fact(start="2023-07-01", end="2024-06-30", value="0"), "growth_pct")
    with pytest.raises(ValueError, match="same metric"):
        calculate(fact(), fact(metric="capex"), "growth_pct")


def test_financial_series_is_as_filed_not_current_restated_values():
    entries = [
        {
            "start": "2024-07-01",
            "end": "2025-06-30",
            "filed": "2025-07-30",
            "val": 100000000,
            "form": "10-K",
            "accn": "0000000001-25-000001",
        },
        {
            "start": "2024-07-01",
            "end": "2025-06-30",
            "filed": "2026-07-30",
            "val": 200000000,
            "form": "10-K",
            "accn": "0000000001-26-000001",
        },
        {
            "start": "2024-07-01",
            "end": "2025-03-31",
            "filed": "2025-04-30",
            "val": 75000000,
            "form": "10-Q",
            "accn": "0000000001-25-000002",
        },
    ]
    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": entries}}}}}
    annual = financial_series(facts, "0000000001", "revenue", "annual", date(2025, 12, 31))
    assert len(annual) == 1 and annual[0].data["value"] == "100000000"
    assert not financial_series(facts, "0000000001", "revenue", "quarterly", date(2025, 12, 31))


def test_amazon_trailing_twelve_months_are_not_fiscal_annual_comparisons():
    entries = [
        {
            "start": "2024-01-01",
            "end": "2024-12-31",
            "filed": "2025-02-07",
            "form": "10-K",
            "accn": "0001018724-25-000004",
            "val": 115877000000,
        },
        {
            "start": "2024-10-01",
            "end": "2025-09-30",
            "filed": "2025-10-31",
            "form": "10-Q",
            "accn": "0001018724-25-000123",
            "val": 130691000000,
        },
        {
            "start": "2024-07-01",
            "end": "2025-06-30",
            "filed": "2025-08-01",
            "form": "10-Q",
            "accn": "0001018724-25-000086",
            "val": 121137000000,
        },
    ]
    facts = {
        "facts": {
            "us-gaap": {"NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": entries}}}
        }
    }
    rows = financial_series(
        facts, "0001018724", "operating_cash_flow", "annual", date(2025, 12, 31)
    )
    assert len(rows) == 1
    assert rows[0].data["end"] == "2024-12-31"


def test_fulltext_ignores_hidden_ixbrl_and_scripts_and_retains_tables():
    html = b"<html><head><script>injected instructions</script></head><body><ix:hidden>secret duplicate</ix:hidden><p>Cloud demand increased.</p><table><tr><td>Revenue</td><td>100</td></tr></table></body></html>"
    text = filing_text(html)
    assert "injected" not in text and "secret" not in text
    assert "Cloud demand increased" in text and "Revenue | 100" in text


def test_fts_queries_are_safe_and_sources_are_snapshot_identified():
    corpus = FilingCorpus()
    try:
        f = Filing(
            "0000000001-25-000001", "10-K", "2025-07-30", "2025-06-30", "https://www.sec.gov/test"
        )
        corpus.add(
            f,
            "Our cloud data center capital expenditure increased because of demand. " * 50,
            "abc123",
        )
        hits = corpus.search('"capital expenditure" OR bad:syntax')
        assert hits and hits[0].sha256 == "abc123"
        assert not corpus.search("无英文查询")
    finally:
        corpus.close()


def test_filing_list_respects_publication_date_and_filing_type(monkeypatch):
    from tradingagents.dataflows.vendors import sec_edgar

    recent = {
        "form": ["10-K", "10-K", "10-Q", "8-K"],
        "filingDate": ["2026-07-30", "2025-07-30", "2025-04-30", "2025-01-01"],
        "accessionNumber": [
            "0000000001-26-000001",
            "0000000001-25-000001",
            "0000000001-25-000002",
            "0000000001-25-000003",
        ],
        "reportDate": ["2026-06-30", "2025-06-30", "2025-03-31", "2025-01-01"],
        "primaryDocument": ["a.htm"] * 4,
    }
    monkeypatch.setattr(
        sec_edgar, "_cached_json", lambda *args: {"filings": {"recent": recent, "files": []}}
    )
    filings = list_filings("0000000001", date(2025, 12, 31))
    assert [f.form for f in filings] == ["10-K", "10-Q"]
    assert all(f.filed <= "2025-12-31" for f in filings)
    with pytest.raises(ValueError):
        filing_url("0000000001", "0000000001-25-000001", "../../passwords")


def report(source_id="S1", quote="Cloud revenue increased year over year."):
    finding = {
        "text": "Cloud revenue is growing but attribution is uncertain.",
        "kind": "inference",
        "citations": [{"source_id": source_id, "quote": quote}],
    }
    return ResearchReport(
        title="Cloud research",
        verdict="mixed",
        answer=finding,
        findings=[finding, finding],
        counterarguments=[finding],
        unknowns=["AI revenue is not disclosed separately."],
        what_would_change=["A separate AI revenue disclosure."],
    )


def test_unknown_citation_and_invented_quote_cannot_pass_verification():
    evidence = Evidence(
        id="S1",
        kind="filing",
        title="10-K",
        url="https://www.sec.gov/test",
        filed="2025-07-30",
        content="Cloud revenue increased year over year. Demand is robust.",
    )
    assert validate_report(report(), {"S1": evidence})["passed"]
    assert not validate_report(report(source_id="fake"), {"S1": evidence})["passed"]
    assert not validate_report(report(quote="AI revenue doubled every quarter."), {"S1": evidence})[
        "passed"
    ]


def test_input_is_trimmed_before_minimum_length_validation():
    with pytest.raises(ValueError):
        ResearchCreate(ticker="MSFT", question=" " * 20)


async def test_api_rejects_non_us_and_future_dates_before_accessing_model():
    from datetime import timedelta

    from fastapi import HTTPException

    from quantcouncil.api.routers.deep_research import create

    for body in [
        ResearchCreate(ticker="600519", question="Check whether cash covers the capital spending."),
        ResearchCreate(
            ticker="MSFT",
            question="Check whether cash covers the capital spending.",
            as_of=date.today() + timedelta(days=1),
        ),
    ]:
        with pytest.raises(HTTPException) as error:
            await create(body, None)
        assert error.value.status_code == 422


def test_baseline_comparisons_only_use_retrieved_and_matching_periods():
    from quantcouncil.deep_research.finance import standard_comparisons

    ocf = fact(metric="operating_cash_flow", value="200000000")
    capex = fact(metric="capex", value="80000000")
    evidence = {item.id: item for item in [ocf, capex]}
    calculated = standard_comparisons(evidence)
    assert len(calculated) == 2
    assert {c.data["result"] for c in calculated} == {"120.00", "40.00"}
    assert all(set(c.inputs) <= evidence.keys() for c in calculated)


@pytest.mark.parametrize("failure", ["quote", "meaning"])
async def test_engine_persists_drafts_and_repairs_failed_checks(monkeypatch, failure):
    from langchain_core.messages import AIMessage

    from quantcouncil.deep_research import engine
    from quantcouncil.deep_research.review import ReportReview, ReviewIssue
    from quantcouncil.deep_research.schemas import ResearchPlan

    filing = Filing(
        "0000000001-25-000001", "10-K", "2025-07-30", "2025-06-30", "https://www.sec.gov/test"
    )
    monkeypatch.setattr(engine.sec_edgar, "cik_for", lambda ticker: "0000000001")
    monkeypatch.setattr(engine, "list_filings", lambda *args: [filing])
    monkeypatch.setattr(
        engine,
        "download_filing",
        lambda f: ("Cloud revenue increased year over year. Demand is robust. " * 10, "abc123"),
    )
    monkeypatch.setattr(engine.sec_edgar, "_cached_json", lambda *args: {})
    saved, events = {}, []
    source_id = filing.accession + ":p0"

    class FakeModel:
        report_calls = 0
        review_calls = 0

        def with_structured_output(self, schema, **kwargs):
            parent = self

            class Structured:
                async def ainvoke(self, messages):
                    parsed = await self.generate(messages)
                    return {
                        "raw": AIMessage(content=parsed.model_dump_json()),
                        "parsed": parsed,
                        "parsing_error": None,
                    }

                async def generate(self, messages):
                    if schema is ReportReview:
                        parent.review_calls += 1
                        if failure == "meaning" and parent.review_calls == 1:
                            return ReportReview(
                                issues=[
                                    ReviewIssue(
                                        location="answer",
                                        explanation="The quote supports growth, not a claim of causality.",
                                        source_ids=[source_id],
                                    )
                                ]
                            )
                        return ReportReview(issues=[])
                    if schema is ResearchPlan:
                        return ResearchPlan(
                            subquestions=["Is cloud growing?", "What is unknown?"],
                            search_queries=["cloud revenue", "demand"],
                            metrics=[],
                        )
                    parent.report_calls += 1
                    return report(
                        source_id=source_id,
                        quote="This quote is invented and must fail."
                        if parent.report_calls == 1 and failure == "quote"
                        else "Cloud revenue increased year over year.",
                    )

            return Structured()

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            return AIMessage(content="Evidence sufficient.")

    async def checkpoint(**changes):
        saved.update(changes)

    async def progress(stage, message):
        events.append(stage)

    fake = FakeModel()
    result = await engine.research(
        "MSFT",
        "Is cloud growing sustainably?",
        date(2025, 12, 31),
        "en",
        {},
        progress,
        checkpoint,
        llm=fake,
    )
    assert result["status"] == "completed" and fake.report_calls == 2
    assert saved["sources"] and saved["report"] and saved["verification"]["passed"]
    assert events[-1] == "verifying"
    assert len(saved["verification"]["attempts"]) == 2
    assert not saved["verification"]["attempts"][0]["verification"]["passed"]
    assert saved["verification"]["semantic_review"]["passed"]


def test_fabricated_numeric_claim_fails_even_when_quote_exists():
    evidence = Evidence(
        id="S1",
        kind="filing",
        title="10-K",
        url="https://www.sec.gov/test",
        filed="2025-07-30",
        content="Revenue grew by 15 percent in 2025.",
    )
    draft = report(quote="Revenue grew by 15 percent in 2025.")
    draft.answer.text = "Revenue grew by 99 percent in 2025."
    checked = validate_report(draft, {"S1": evidence})
    assert not checked["passed"]
    assert any("99" in error for error in checked["errors"])


def test_model_cannot_rescale_numbers_or_invent_fcf_without_calculation_source():
    evidence = fact()
    draft = report(source_id=evidence.id, quote=evidence.content)
    draft.answer.text = "Revenue reached 1 亿美元 and FCF was 100 USD million."
    checked = validate_report(draft, {evidence.id: evidence})
    assert not checked["passed"]
    assert any("calculation source" in error for error in checked["errors"])


def test_iso_dates_and_chinese_dates_have_the_same_numeric_components():
    evidence = Evidence(
        id="S1",
        kind="filing",
        title="10-K",
        url="https://www.sec.gov/test",
        filed="2025-07-30",
        content="The company filed its report on 2025-07-30.",
    )
    draft = report(quote="The company filed its report on 2025-07-30.")
    draft.answer.text = "报告于2025年7月30日披露。"
    assert validate_report(draft, {"S1": evidence})["passed"]


def test_fcf_limitation_is_not_confused_with_a_new_calculation():
    source = Evidence(
        id="S1",
        kind="filing",
        title="10-K",
        url="https://www.sec.gov/test",
        filed="2026-07-29",
        content="Finance leases were 24,608 million. Cash capex excludes finance leases.",
    )
    draft = report(quote="Finance leases were 24,608 million. Cash capex excludes finance leases.")
    draft.answer.text = (
        "融资租赁金额为24,608 million。上述自由现金流仅是现金口径代理，不能表示全部投入承诺。"
    )
    assert validate_report(draft, {"S1": source})["passed"]


@pytest.mark.parametrize(
    "text",
    [
        "Revenue was 100 billion, a very large reported revenue.",
        "公司收入为100亿美元，收入规模非常大。",
    ],
)
def test_same_number_in_quote_does_not_authorize_a_different_unit(text):
    source = fact()
    draft = report(source_id=source.id, quote=source.content)
    draft.answer.text = text
    checked = validate_report(draft, {source.id: source})
    assert not checked["passed"]
    assert any("unit mismatch" in error for error in checked["errors"])


def test_uncited_sections_cannot_hide_factual_numbers():
    source = fact()
    draft = report(source_id=source.id, quote=source.content)
    draft.unknowns = ["Asset lives are 2–6 years, affecting depreciation."]
    assert not validate_report(draft, {source.id: source})["passed"]


@pytest.mark.parametrize("finish_reason", ["stop", "length"])
async def test_empty_or_truncated_model_output_is_retained_and_fails_clearly(finish_reason):
    from langchain_core.messages import AIMessage, HumanMessage

    from quantcouncil.deep_research.generation import structured
    from quantcouncil.deep_research.schemas import ResearchPlan

    saved = []

    class Model:
        model_name = "deepseek-v4-pro"

        def with_structured_output(self, schema, **kwargs):
            assert kwargs == {"include_raw": True, "method": "json_mode"}
            return self

        async def ainvoke(self, messages):
            assert "JSON schema" in messages[-1].content
            return {
                "raw": AIMessage(
                    content='{"partial":', response_metadata={"finish_reason": finish_reason}
                ),
                "parsed": None,
                "parsing_error": ValueError("incomplete JSON"),
            }

    async def record(output):
        saved.append(output)

    with pytest.raises(ValueError, match="original output retained"):
        await structured(Model(), ResearchPlan, [HumanMessage("Plan research")], record)
    assert saved[0]["content"] == '{"partial":'
    assert saved[0]["finish_reason"] == finish_reason


def test_apple_cash_return_coverage_uses_exact_amounts_and_keeps_input_chain():
    from quantcouncil.deep_research.finance import standard_comparisons

    rows = [
        fact(metric=metric, value=str(amount * 1000000), cik="0000320193")
        for metric, amount in [
            ("operating_cash_flow", 111482),
            ("capex", 12715),
            ("repurchases", 90711),
            ("dividends", 15421),
        ]
    ]
    sources = {row.id: row for row in rows}
    calculations = standard_comparisons(sources)
    sources.update({row.id: row for row in calculations})
    residual = next(row for row in calculations if row.data["result"] == "-7365.00")
    assert all(sources[key].kind == "calculation" for key in residual.inputs)
    assert residual.data["basis"]["value"] == "-7365000000"
    assert residual.title.endswith(f"− ({sources[residual.inputs[1]].title})")
    assert len(residual.content) <= 600
    assert any(row.data["result"] == "106132.00" for row in calculations)
    ratio = calculate(rows[1], rows[0], "ratio_pct")
    with pytest.raises(ValueError, match="monetary"):
        calculate(ratio, rows[0], "sum")
    with pytest.raises(ValueError, match="Companies"):
        calculate(rows[0], fact(cik="0001018724"), "difference")
    with pytest.raises(ValueError, match="identical reporting periods"):
        calculate(residual, fact(cik="0000320193", start="2023-07-01", end="2024-06-30"), "sum")


def test_accounting_parentheses_support_a_negative_number():
    source = fact()
    source.content = "Operating income (loss) | ( 2,656 ) USD million"
    finding = {"kind": "fact", "text": "Operating loss was -2656 USD million", "citations": [{"source_id": source.id, "quote": source.content}]}
    report = ResearchReport(title="Reported loss", verdict="supported", answer=finding, findings=[finding, finding], counterarguments=[finding], unknowns=["Future results remain uncertain"], what_would_change=["New results could change the answer"])
    assert validate_report(report, {source.id: source})["passed"]


def test_calendar_year_wording_is_not_an_uncited_financial_quantity():
    source = fact()
    report = ResearchReport(
        title="Evidence limits",
        verdict="insufficient",
        answer={"kind": "inference", "text": "Retrieved evidence does not resolve the question.", "citations": [{"source_id": source.id, "quote": source.content}]},
        findings=[{"kind": "fact", "text": "Revenue as filed: 100 USD million", "citations": [{"source_id": source.id, "quote": source.content}]}] * 2,
        counterarguments=[{"kind": "inference", "text": "Retrieved evidence does not resolve the question.", "citations": [{"source_id": source.id, "quote": source.content}]}],
        unknowns=["在检索证据中未找到2025日历年全年数据。参见发现1、2。"],
        what_would_change=["若提供2025自然年可比数据，可以扩展比较。"],
    )
    assert validate_report(report, {source.id: source})["passed"]
    report.unknowns = ["参见发现2、99。"]
    assert not validate_report(report, {source.id: source})["passed"]


def test_signed_residual_can_be_expressed_as_a_positive_shortfall_not_positive_income():
    source = Evidence(
        id="C1",
        kind="calculation",
        title="Coverage residual",
        url="https://www.sec.gov/test",
        filed="2025-10-31",
        content="difference: -7365.00 USD million; OCF minus capex minus shareholder cash returns.",
    )
    draft = report(source_id=source.id, quote=source.content)
    draft.answer.text = "现金流残差为-7,365.00 USD million，因此缺口为7,365 USD million。"
    draft.title = "2025年现金覆盖分析"
    assert validate_report(draft, {source.id: source})["passed"]
    draft.answer.text = "经营现金流为7,365 USD million，现金流规模足够。"
    assert not validate_report(draft, {source.id: source})["passed"]


def test_negligible_credit_cost_supports_only_an_explicit_approximation():
    source = Evidence(
        id="S1",
        kind="filing",
        title="10-K",
        url="https://www.sec.gov/test",
        filed="2025-01-30",
        content="Automotive regulatory credits have negligible incremental costs associated with them.",
    )
    draft = report(quote=source.content)
    draft.answer.text = "积分成本≈0只是近似假设，并非公司披露的实测成本。"
    assert validate_report(draft, {source.id: source})["passed"]
    draft.answer.text = "公司披露积分成本为0 USD million，是精确的报告金额。"
    assert not validate_report(draft, {source.id: source})["passed"]


def test_quote_restoration_never_skips_rows_or_changes_filings():
    from quantcouncil.deep_research.citations import canonicalize_citations

    def source(id, content, accession="same", sha256="samehash"):
        return Evidence(
            id=id,
            kind="filing",
            title="10-K",
            url="https://www.sec.gov/test",
            filed="2025-02-07",
            content=content,
            accession=accession,
            sha256=sha256,
        )

    one = source("S1", "AWS | 53,267 | Corporate | 1,494 | Consolidated | $ | 85,752")
    draft = report(quote="AWS | $ | 53,267 | Consolidated | $ | 85,752")
    assert not canonicalize_citations(draft, {"S1": one})
    assert not validate_report(draft, {"S1": one})["passed"]
    draft = report(quote="AWS | $ | 53,267 | Corporate | 1,494 | Consolidated | $ | 85,752")
    edits = canonicalize_citations(draft, {"S1": one})
    assert edits and draft.answer.citations[0].quote == one.content
    draft = report(quote="The company discloses cash investments in technology infrastructure.")
    other = source("S2", draft.answer.citations[0].quote, accession="different")
    assert not canonicalize_citations(draft, {"S1": one, "S2": other})
    neighbour = source("S3", draft.answer.citations[0].quote)
    edits = canonicalize_citations(draft, {"S1": one, "S3": neighbour})
    assert edits and draft.answer.citations[0].source_id == "S3"


def test_comparative_years_in_table_headers_do_not_authorize_uncited_amounts():
    source = Evidence(
        id="S1",
        kind="filing",
        title="10-K 2024",
        url="https://www.sec.gov/test",
        filed="2025-02-07",
        content="Year ended | 2024 | 2023 | 2022. Revenue | 100 | 90 | 80. Other assets | 999.",
    )
    draft = report(quote="Revenue | 100 | 90 | 80.")
    draft.answer.text = "2023年收入为90 USD million，年度收入低于下一年。"
    draft.unknowns = ["本次2025年度10-K未找到客户构成数据。"]
    draft.what_would_change = ["若后续2025年度10-K补充披露客户构成，可重新评估。"]
    assert validate_report(draft, {source.id: source})["passed"]
    draft.answer.text = "2023年收入为999 USD million，该收入增长明显。"
    assert not validate_report(draft, {source.id: source})["passed"]
    draft.answer.text = "2021年收入为90 USD million，该收入增长明显。"
    assert not validate_report(draft, {source.id: source})["passed"]


@pytest.mark.parametrize("stage", ["writer", "reviewer"])
async def test_deepseek_report_effort_is_bounded_without_lowering_review_effort(stage):
    from langchain_core.messages import AIMessage, HumanMessage

    from quantcouncil.deep_research.generation import structured
    from quantcouncil.deep_research.review import ReportReview

    schema = ResearchReport if stage == "writer" else ReportReview
    parsed = report() if stage == "writer" else ReportReview(issues=[])
    saved = []

    class Model:
        model_name = "deepseek-v4-pro"
        openai_api_base = "https://api.deepseek.com"
        reasoning_effort = "high"

        def with_structured_output(self, target, **kwargs):
            assert kwargs.get("reasoning_effort") == ("low" if stage == "writer" else None)
            return self

        async def ainvoke(self, messages):
            return {
                "raw": AIMessage(content=parsed.model_dump_json()),
                "parsed": parsed,
                "parsing_error": None,
            }

    async def record(output):
        saved.append(output)

    model = Model()
    await structured(model, schema, [HumanMessage("Write JSON")], record)
    assert model.reasoning_effort == "high"
    assert saved[0]["request_options"].get("reasoning_effort") == (
        "low" if stage == "writer" else None
    )
