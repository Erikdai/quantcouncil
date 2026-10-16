"""Restore exact table layout or a neighbouring passage ID, never paraphrase evidence."""

from quantcouncil.deep_research.schemas import Evidence, ResearchReport


def _exact_span(content: str, quote: str) -> str | None:
    table = "|" in quote

    def ignored(char):
        return char.isspace() or (table and char in "|$")

    needle = "".join(c for c in quote if not ignored(c))
    positions = [i for i, c in enumerate(content) if not ignored(c)]
    haystack = "".join(content[i] for i in positions)
    if len(needle) < 20 or haystack.count(needle) != 1:
        return None
    start = haystack.index(needle)
    exact = content[positions[start] : positions[start + len(needle) - 1] + 1]
    return exact if 12 <= len(exact) <= 600 else None


def canonicalize_citations(report: ResearchReport, sources: dict[str, Evidence]) -> list[dict]:
    edits = []
    for finding in [report.answer, *report.findings, *report.counterarguments]:
        for citation in finding.citations:
            source = sources.get(citation.source_id)
            if source is None or citation.quote in source.content:
                continue
            # A quote crossing one chunk's edge may be wholly in its overlapping
            # neighbour. Never move it to another filing, company or snapshot.
            candidates = [
                source,
                *(
                    s
                    for s in sources.values()
                    if s.id != source.id
                    and source.kind == s.kind == "filing"
                    and source.accession
                    and s.accession == source.accession
                    and s.sha256 == source.sha256
                ),
            ]
            for candidate in candidates:
                exact = _exact_span(candidate.content, citation.quote)
                if exact is not None:
                    edits.append(
                        {
                            "before_source_id": citation.source_id,
                            "source_id": candidate.id,
                            "before": citation.quote,
                            "after": exact,
                        }
                    )
                    citation.source_id, citation.quote = candidate.id, exact
                    break
    return edits
