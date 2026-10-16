"""Fresh discovery and immutable filing snapshots; no cached index as freshness proof."""

import hashlib
import json
import re
from datetime import UTC, date, datetime, timedelta

from quantcouncil.deep_research.finance import METRICS
from quantcouncil.deep_research.schemas import Evidence
from quantcouncil.deep_research.sec import Filing, download_filing, filing_url, passages
from quantcouncil.deep_research.segments import filing_facts
from quantcouncil.markets import Instrument, agent_config
from quantcouncil.thesis_tracking.schemas import Snapshot
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.vendors import sec_edgar

FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A"}
METRIC_KEYS = tuple(k for k in METRICS if k not in ("cash", "assets"))


def collect_snapshot(ticker: str, as_of: date) -> Snapshot:
    with run_config(agent_config(Instrument(ticker, "US"))):
        cik = sec_edgar.cik_for(ticker)
        if not cik:
            raise ValueError("No domestic SEC filer found")
        # Discovery must make a real request; immutable accession HTML is still reused.
        index = sec_edgar._fetch_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
        batches = [index["filings"]["recent"]]
        oldest = str(as_of - timedelta(days=3 * 366))
        for item in index["filings"].get("files", []):
            if item["filingFrom"] <= str(as_of) and item["filingTo"] >= oldest:
                if not re.fullmatch(r"CIK\d+-submissions-\d+\.json", item["name"]):
                    raise ValueError("Invalid submission page identity")
                batches.append(
                    sec_edgar._fetch_json("https://data.sec.gov/submissions/" + item["name"])
                )
        filings = {}
        for batch in batches:
            for i, form in enumerate(batch["form"]):
                filed = batch["filingDate"][i]
                if form not in FORMS or not oldest <= filed <= str(as_of):
                    continue
                accn = batch["accessionNumber"][i]
                filings[accn] = Filing(
                    accn,
                    form,
                    filed,
                    batch["reportDate"][i],
                    filing_url(cik, accn, batch["primaryDocument"][i]),
                )
        if not filings or len(filings) > 40:
            raise ValueError(
                "Cannot obtain a complete bounded three-year filing window (1–40 filings required)"
            )
        sources, excerpts, manifest = {}, [], []
        for filing in sorted(filings.values(), key=lambda f: (f.filed, f.accession)):
            text, digest = download_filing(filing)
            manifest.append({**filing.__dict__, "sha256": digest})
            for source in filing_facts(filing, cik, METRIC_KEYS):
                span = (
                    date.fromisoformat(source.data["end"])
                    - date.fromisoformat(source.data["start"])
                ).days
                if source.data["end"] <= str(as_of) and not (
                    filing.form.startswith("10-Q") and span >= 330
                ):
                    key = (source.data["metric"], source.data["start"], source.data["end"])
                    sources[key] = source
            # Scope text stays exact and hash-bound, distinct from model explanations.
            relevant = [
                p
                for _, _, p in passages(text)
                if re.search(
                    r"reportable segments|organized.{0,60}into|reclassif|segment reporting|change.*segment",
                    p,
                    re.I,
                )
            ]
            # Roster declarations outrank generic reclassification mentions, which
            # otherwise exhaust the bounded excerpts before the segment note.
            relevant.sort(
                key=lambda p: (
                    not bool(re.search(r"organized.{0,60}into", p, re.I)),
                    not bool(re.search(r"reportable segments", p, re.I)),
                )
            )
            for n, content in enumerate(relevant[:3]):
                excerpts.append(
                    Evidence(
                        id=f"{filing.accession}:scope:{n}",
                        kind="filing",
                        title=f"{filing.form} scope {filing.period}",
                        url=filing.url,
                        filed=filing.filed,
                        accession=filing.accession,
                        sha256=digest,
                        content=content,
                    )
                )
        # Q trailing-year values were excluded above; later amendments replace
        # facts only within the identical metric and cumulative period.
        fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        return Snapshot(
            ticker=ticker,
            as_of=as_of,
            fetched_at=datetime.now(UTC).isoformat(),
            manifest=manifest,
            sources=list(sources.values()),
            excerpts=excerpts,
            fingerprint=fingerprint,
        )
