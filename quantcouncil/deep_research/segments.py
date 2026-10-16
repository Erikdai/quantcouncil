"""Operating profit from visible inline XBRL, preserving explicit segment contexts."""

import hashlib
import os
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from bs4 import BeautifulSoup

from quantcouncil.deep_research.finance import calculate
from quantcouncil.deep_research.schemas import Evidence


def operating_income_facts(filing, cik: str) -> list[Evidence]:
    raw = (
        Path(os.getenv("QUANTCOUNCIL_DATA_DIR", ".quantcouncil"))
        / "sec_filings"
        / f"{filing.accession}.html"
    ).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    soup = BeautifulSoup(re.sub(rb"<\?xml[^>]*\?>", b"", raw, count=1), "lxml")
    contexts = {c.get("id"): c for c in soup.find_all("xbrli:context")}
    out = {}
    for cell in soup.find_all("ix:nonfraction"):
        if cell.get("name") != "us-gaap:OperatingIncomeLoss" or cell.find_parent("ix:hidden"):
            continue
        context = contexts.get(cell.get("contextref"))
        unit = soup.find("xbrli:unit", id=cell.get("unitref"))
        if context is None or unit is None or unit.get_text(strip=True) != "iso4217:USD":
            continue
        entity = context.find("xbrli:identifier")
        if entity is None or entity.get_text(strip=True).lstrip("0") != cik.lstrip("0"):
            continue
        members = context.find_all("xbrldi:explicitmember")
        if context.find("xbrldi:typedmember") or len(members) > 1:
            continue
        if members and members[0].get("dimension") != "us-gaap:StatementBusinessSegmentsAxis":
            continue
        start, end = context.find("xbrli:startdate"), context.find("xbrli:enddate")
        if start is None or end is None:
            continue
        start, end = start.get_text(strip=True), end.get_text(strip=True)
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
        if not 60 <= days <= 400:
            continue
        segment = members[0].get_text(strip=True) if members else "consolidated"
        literal = cell.get_text("", strip=True).replace(",", "").replace(" ", "")
        if literal in ("—", "–", "-"):
            literal = "0"
        try:
            value = Decimal(literal) * Decimal(10) ** int(cell.get("scale", 0))
            if cell.get("sign") == "-":
                value = -value
        except (InvalidOperation, ValueError):
            continue
        metric = f"operating_income:{segment}"
        identity = f"{cik}:{filing.accession}:{metric}:{start}:{end}"
        key = "F" + hashlib.sha256(identity.encode()).hexdigest()[:14]
        content = f"Operating income; segment {segment}: {value / Decimal(1000000)} USD million; period {start} to {end}; filed {filing.filed}; form {filing.form}; inline XBRL us-gaap:OperatingIncomeLoss; context {cell.get('contextref')}."
        out[(segment, start, end)] = Evidence(
            id=key,
            kind="financial",
            title=f"Operating income · {segment} · {start} to {end}",
            url=filing.url,
            filed=filing.filed,
            accession=filing.accession,
            sha256=digest,
            content=content,
            data={
                "cik": cik,
                "metric": metric,
                "segment": segment,
                "start": start,
                "end": end,
                "value": str(value),
                "unit": "USD",
                "frequency": "as_reported",
                "tag": "OperatingIncomeLoss",
                "context": cell.get("contextref"),
                "provenance": "visible_inline_xbrl",
            },
        )
    return list(out.values())


def profit_contributions(facts: list[Evidence]) -> list[Evidence]:
    """Compare like-duration year-on-year changes, then segment/group change ratios."""
    selected = {}
    for row in sorted(facts, key=lambda r: (r.filed, r.accession or "")):
        d = row.data
        selected[(d["metric"], d["start"], d["end"])] = row
    rows = list(selected.values())
    changes = []
    for row in rows:
        d = row.data
        end = date.fromisoformat(d["end"])
        span = (end - date.fromisoformat(d["start"])).days
        prior = [
            other
            for other in rows
            if other.data["metric"] == d["metric"]
            and 350 <= (end - date.fromisoformat(other.data["end"])).days <= 380
            and abs(
                span
                - (
                    date.fromisoformat(other.data["end"]) - date.fromisoformat(other.data["start"])
                ).days
            )
            <= 15
        ]
        if prior:
            changes.append(calculate(row, max(prior, key=lambda r: r.data["end"]), "change"))
    result = [*rows, *changes]
    for row in changes:
        if row.data["basis"]["metric"] == "change(operating_income:consolidated)":
            continue
        for group in changes:
            if (
                group.data["basis"]["metric"] == "change(operating_income:consolidated)"
                and (row.data["basis"]["start"], row.data["basis"]["end"])
                == (group.data["basis"]["start"], group.data["basis"]["end"])
                and Decimal(group.data["basis"]["value"]) > 0
            ):
                result.append(calculate(row, group, "ratio_pct"))
    return result
