"""Immutable SEC primary-document snapshots and local SQLite FTS5 retrieval.

FTS5 is the standard-library search engine; no embedding model or extra service
is needed to search four filings. The durable evidence stays in PostgreSQL and
raw downloaded filings stay in the existing shared data directory.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from quantcouncil.deep_research.schemas import Evidence
from tradingagents.dataflows.files import replace_file
from tradingagents.dataflows.vendors import sec_edgar


@dataclass(frozen=True)
class Filing:
    accession: str
    form: str
    filed: str
    period: str
    url: str


def filing_url(cik: str, accession: str, document: str) -> str:
    if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) or "/" in document or "\\" in document:
        raise ValueError("Invalid SEC document identity")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{quote(document)}"


def list_filings(cik: str, as_of: date) -> list[Filing]:
    data = sec_edgar._cached_json(
        f"https://data.sec.gov/submissions/CIK{cik}.json", f"submissions-{cik}.json"
    )
    batches = [data["filings"]["recent"]]
    # Older point-in-time requests need the SEC's paginated submission files.
    for item in data["filings"].get("files", []):
        if item["filingFrom"] <= str(as_of):
            name = item["name"]
            if not re.fullmatch(r"CIK\d+-submissions-\d+\.json", name):
                continue
            batches.append(sec_edgar._cached_json(f"https://data.sec.gov/submissions/{name}", name))
            if len(batches) >= 4:
                break
    found = {}
    for batch in batches:
        for i, form in enumerate(batch["form"]):
            filed = batch["filingDate"][i]
            if form not in ("10-K", "10-Q") or filed > str(as_of):
                continue
            accession = batch["accessionNumber"][i]
            found[accession] = Filing(
                accession,
                form,
                filed,
                batch["reportDate"][i],
                filing_url(cik, accession, batch["primaryDocument"][i]),
            )
    ordered = sorted(found.values(), key=lambda f: (f.filed, f.accession), reverse=True)
    # Two annuals give comparable years; two quarterlies keep current developments.
    selected = [f for f in ordered if f.form == "10-K"][:2] + [
        f for f in ordered if f.form == "10-Q"
    ][:2]
    if not selected:
        raise ValueError(
            "No 10-K/10-Q filed by this date. This version supports US domestic SEC filers."
        )
    return sorted(selected, key=lambda f: f.filed, reverse=True)


def filing_text(raw: bytes) -> str:
    # SEC inline-XBRL uses HTML with an XML declaration; keep the HTML parser.
    raw = re.sub(rb"<\?xml[^>]*\?>", b"", raw, count=1)
    soup = BeautifulSoup(raw, "lxml")
    for element in soup.find_all(["script", "style", "head", "noscript", "svg", "ix:hidden"]):
        element.decompose()
    for table in soup.find_all("table"):
        if table.parent is None:
            continue
        rows = [
            " | ".join(cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"]))
            for row in table.find_all("tr")
        ]
        table.replace_with(soup.new_string("\n" + "\n".join(rows) + "\n"))
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def passages(text: str, size: int = 1800, overlap: int = 600):
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = text.rfind(" ", start + size // 2, end)
            if cut > start:
                end = cut
        yield start, end, text[start:end]
        if end == len(text):
            break
        start = end - overlap


def download_filing(filing: Filing) -> tuple[str, str]:
    root = Path(os.getenv("QUANTCOUNCIL_DATA_DIR", ".quantcouncil")) / "sec_filings"
    path = root / f"{filing.accession}.html"
    if path.exists():
        raw = path.read_bytes()
    else:
        response = requests.get(
            filing.url, headers={"User-Agent": sec_edgar._user_agent()}, timeout=40
        )
        response.raise_for_status()
        raw = response.content
        if len(raw) > 20_000_000:
            raise ValueError("SEC filing exceeds the 20 MB document limit")
        # A block/empty response must never poison the immutable filing cache.
        text = filing_text(raw)
        if len(text) < 5000:
            raise ValueError("SEC filing did not contain usable full text")
        root.mkdir(parents=True, exist_ok=True)
        replace_file(path, lambda temp: Path(temp).write_bytes(raw))
    return filing_text(raw), hashlib.sha256(raw).hexdigest()


class FilingCorpus:
    def __init__(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.execute(
            "CREATE VIRTUAL TABLE passages USING fts5(id UNINDEXED, content, tokenize='porter unicode61')"
        )
        self.sources: dict[str, Evidence] = {}
        self.manifest: list[dict] = []

    def add(self, filing: Filing, text: str, digest: str):
        self.manifest.append({**filing.__dict__, "sha256": digest, "characters": len(text)})
        for index, (start, end, content) in enumerate(passages(text)):
            key = f"{filing.accession}:p{index}"
            self.sources[key] = Evidence(
                id=key,
                kind="filing",
                title=f"{filing.form} · {filing.period} · passage {index}",
                url=filing.url,
                filed=filing.filed,
                content=content,
                accession=filing.accession,
                sha256=digest,
                data={"start": start, "end": end},
            )
            self.db.execute("INSERT INTO passages VALUES (?, ?)", (key, content))
        self.db.commit()

    def search(self, query: str, limit: int = 5) -> list[Evidence]:
        terms = re.findall(r"[a-zA-Z][a-zA-Z0-9]{2,}", query)[:20]
        if not terms:
            return []
        expression = " OR ".join(f'"{term}"' for term in terms)
        rows = self.db.execute(
            "SELECT id FROM passages WHERE passages MATCH ? ORDER BY bm25(passages) LIMIT ?",
            (expression, min(max(limit, 1), 8)),
        ).fetchall()
        return [self.sources[row[0]] for row in rows]

    def close(self):
        self.db.close()
