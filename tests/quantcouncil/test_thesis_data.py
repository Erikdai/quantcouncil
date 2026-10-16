from datetime import date

import pytest

from quantcouncil.thesis_tracking import data
from tests.quantcouncil.test_thesis_rules import fact


def test_discovery_is_fresh_amendments_replace_only_same_period(monkeypatch):
    calls = []
    batch = {
        "form": ["10-K", "10-K/A", "10-K"],
        "filingDate": ["2025-02-01", "2025-03-01", "2026-02-01"],
        "accessionNumber": ["original", "amended", "future"],
        "reportDate": ["2024-12-31"] * 3,
        "primaryDocument": ["annual.htm"] * 3,
    }
    monkeypatch.setattr(data.sec_edgar, "cik_for", lambda _: "0000000001")

    def fresh(url):
        calls.append(url)
        return {"filings": {"recent": batch, "files": []}}

    monkeypatch.setattr(data.sec_edgar, "_fetch_json", fresh)
    monkeypatch.setattr(data, "filing_url", lambda *args: "https://www.sec.gov/annual.htm")
    monkeypatch.setattr(data, "download_filing", lambda f: ("No segment changes.", f.accession))

    monkeypatch.setattr(
        data,
        "passages",
        lambda _: [
            (0, 1, "Reclassification of investments"),
            (1, 2, "Reclassification of taxes"),
            (2, 3, "Reclassification of debt"),
            (
                3,
                4,
                "We have organized our operations into three segments: North America, International, and AWS.",
            ),
        ],
    )

    def parsed(filing, *_):
        row = fact("revenue", 100 if filing.accession == "original" else 90)
        row.filed, row.accession = filing.filed, filing.accession
        return [row]

    monkeypatch.setattr(data, "filing_facts", parsed)
    before = data.collect_snapshot("TEST", date(2025, 2, 28))
    after = data.collect_snapshot("TEST", date(2025, 3, 31))
    assert "three segments" in after.excerpts[0].content
    assert len(calls) == 2  # Discovery is requested on every check, even with cached HTML.
    assert before.sources[0].data["value"] == "100000000"
    assert after.sources[0].data["value"] == "90000000"
    assert before.fingerprint != after.fingerprint
    assert [f["accession"] for f in after.manifest] == ["original", "amended"]

    def unavailable(_):
        raise OSError("SEC unavailable")

    monkeypatch.setattr(data.sec_edgar, "_fetch_json", unavailable)
    with pytest.raises(OSError, match="SEC unavailable"):
        data.collect_snapshot("TEST", date(2025, 3, 31))
