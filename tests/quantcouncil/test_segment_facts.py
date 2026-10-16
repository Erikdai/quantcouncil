from decimal import Decimal

import pytest

from quantcouncil.deep_research.finance import calculate
from quantcouncil.deep_research.sec import Filing
from quantcouncil.deep_research.segments import filing_facts, profit_contributions


def test_original_inline_xbrl_segments_generate_contributions(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTCOUNCIL_DATA_DIR", str(tmp_path))
    filing = Filing(
        "0001018724-25-000004", "10-K", "2025-02-07", "2024-12-31", "https://www.sec.gov/test"
    )
    parts = ['<html><xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>']
    for member, values in [
        ("amzn:AmazonWebServicesSegmentMember", [24631, 39834]),
        (None, [36852, 68593]),
    ]:
        for year, value in zip([2023, 2024], values, strict=True):
            key = f"c{year}{member or 'group'}"
            segment = (
                f'<xbrli:segment><xbrldi:explicitmember dimension="us-gaap:StatementBusinessSegmentsAxis">{member}</xbrldi:explicitmember></xbrli:segment>'
                if member
                else ""
            )
            parts.append(
                f'<xbrli:context id="{key}"><xbrli:entity><xbrli:identifier>0001018724</xbrli:identifier>{segment}</xbrli:entity><xbrli:period><xbrli:startdate>{year}-01-01</xbrli:startdate><xbrli:enddate>{year}-12-31</xbrli:enddate></xbrli:period></xbrli:context><ix:nonfraction name="us-gaap:OperatingIncomeLoss" contextref="{key}" unitref="usd" scale="6">{value:,}</ix:nonfraction>'
            )
    parts.append(
        '<ix:hidden><ix:nonfraction name="us-gaap:OperatingIncomeLoss" contextref="c2024group" unitref="usd" scale="6">999999</ix:nonfraction></ix:hidden></html>'
    )
    root = tmp_path / "sec_filings"
    root.mkdir()
    (root / f"{filing.accession}.html").write_text("".join(parts))
    facts = filing_facts(filing, "0001018724")
    assert len(facts) == 4
    assert all(f.sha256 and f.data["provenance"] == "visible_inline_xbrl" for f in facts)
    results = profit_contributions(facts)
    ratio = next(r for r in results if r.kind == "calculation" and r.data["unit"] == "%")
    assert ratio.data["result"] == "47.90"
    changes = {r.id: r for r in results if r.kind == "calculation" and r.data.get("basis")}
    assert Decimal(changes[ratio.inputs[0]].data["basis"]["value"]) == 15203000000
    assert Decimal(changes[ratio.inputs[1]].data["basis"]["value"]) == 31741000000
    assert not filing_facts(filing, "0000000001")
    current, prior = (
        sorted(facts, key=lambda r: r.data["end"], reverse=True)[0],
        sorted(facts, key=lambda r: r.data["end"])[0],
    )
    with pytest.raises(ValueError, match="same metric"):
        calculate(
            current, next(f for f in facts if f.data["metric"] != current.data["metric"]), "change"
        )
    assert current.data["end"] > prior.data["end"]


def test_profit_change_allows_turnaround_but_rejects_ytd_vs_full_year():
    from quantcouncil.deep_research.schemas import Evidence

    def source(key, start, end, value):
        return Evidence(
            id=key,
            kind="financial",
            title=key,
            url="https://www.sec.gov/test",
            filed="2025-02-07",
            content="As-filed operating income",
            data={
                "cik": "1",
                "metric": "operating_income:International",
                "unit": "USD",
                "frequency": "as_reported",
                "start": start,
                "end": end,
                "value": value,
            },
        )

    older = source("old", "2023-01-01", "2023-12-31", "-2656000000")
    newer = source("new", "2024-01-01", "2024-12-31", "3792000000")
    result = calculate(newer, older, "change")
    assert result.data["result"] == "6448.00"
    assert result.data["basis"]["value"] == "6448000000"
    with pytest.raises(ValueError, match="durations"):
        calculate(source("ytd", "2024-01-01", "2024-09-30", "100"), older, "change")


def test_general_financial_parser_prefers_standard_tag_and_blocks_conflicts(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTCOUNCIL_DATA_DIR", str(tmp_path))
    filing = Filing(
        "0000000001-25-000001", "10-K", "2025-02-01", "2024-12-31", "https://www.sec.gov/test"
    )
    root = tmp_path / "sec_filings"
    root.mkdir()
    path = root / f"{filing.accession}.html"
    header = """<html><xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
    <xbrli:context id="c"><xbrli:entity><xbrli:identifier>1</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startdate>2024-01-01</xbrli:startdate><xbrli:enddate>2024-12-31</xbrli:enddate></xbrli:period></xbrli:context>"""

    def cell(tag, value):
        return f'<ix:nonfraction name="us-gaap:{tag}" contextref="c" unitref="usd" scale="6">{value}</ix:nonfraction>'

    preferred = cell("RevenueFromContractWithCustomerExcludingAssessedTax", 100)
    path.write_text(
        header
        + preferred
        + cell("Revenues", 90)
        + "<ix:hidden>"
        + cell("RevenueFromContractWithCustomerExcludingAssessedTax", 999)
        + "</ix:hidden></html>"
    )
    facts = filing_facts(filing, "1", ("revenue",))
    assert len(facts) == 1 and facts[0].data["value"] == "100000000"
    path.write_text(
        header
        + preferred
        + cell("RevenueFromContractWithCustomerExcludingAssessedTax", 101)
        + "</html>"
    )
    with pytest.raises(ValueError, match="Conflicting inline XBRL"):
        filing_facts(filing, "1", ("revenue",))
