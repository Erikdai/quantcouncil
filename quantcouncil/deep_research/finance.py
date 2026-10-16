"""As-filed SEC facts and deterministic comparisons, never model-entered numbers."""

from __future__ import annotations

import contextlib
import hashlib
import json
from datetime import date
from decimal import Decimal

from quantcouncil.deep_research.schemas import Evidence

METRICS = {
    "revenue": (
        "Revenue",
        ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"),
    ),
    "operating_income": ("Operating income", ("OperatingIncomeLoss",)),
    "net_income": ("Net income", ("NetIncomeLoss",)),
    "operating_cash_flow": (
        "Operating cash flow",
        (
            "NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        ),
    ),
    "capex": (
        "Reported cash capital asset purchases",
        ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"),
    ),
    "cash": ("Cash and equivalents", ("CashAndCashEquivalentsAtCarryingValue",)),
    "assets": ("Total assets", ("Assets",)),
    "repurchases": ("Cash share repurchases", ("PaymentsForRepurchaseOfCommonStock",)),
    "dividends": ("Cash dividends", ("PaymentsOfDividends",)),
}


def financial_series(
    facts: dict, cik: str, metric: str, frequency: str, as_of: date
) -> list[Evidence]:
    label, tags = METRICS[metric]
    candidates = {}
    for tag in reversed(tags):  # Preferred tag replaces an alternate for the same period.
        by_period = {}
        for fact in (
            facts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get("USD", [])
        ):
            if (
                fact["filed"] > str(as_of)
                or fact["end"] > str(as_of)
                or fact.get("form") not in ("10-K", "10-K/A", "10-Q", "10-Q/A")
                or (frequency == "annual" and not fact["form"].startswith("10-K"))
            ):
                continue
            start, end = fact.get("start"), fact["end"]
            if start:
                duration = (date.fromisoformat(end) - date.fromisoformat(start)).days
                low, high = (330, 400) if frequency == "annual" else (60, 115)
                if not low <= duration <= high:
                    continue
            elif frequency == "annual" and not fact["form"].startswith("10-K"):
                continue
            key = (start, end)
            prior = by_period.get(key)
            if prior is None or (fact["filed"], fact.get("accn", "")) > (
                prior["filed"],
                prior.get("accn", ""),
            ):
                by_period[key] = {**fact, "tag": tag}
        candidates.update(by_period)
    digest = hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()
    selected = sorted(
        candidates.values(), key=lambda f: (f["end"], f.get("start", "")), reverse=True
    )[:6]
    out = []
    for fact in selected:
        accn = fact["accn"]
        identity = f"{cik}:{metric}:{fact['tag']}:{fact.get('start', '')}:{fact['end']}:{accn}"
        key = "F" + hashlib.sha256(identity.encode()).hexdigest()[:14]
        start = fact.get("start")
        period = f"{start} to {fact['end']}" if start else f"at {fact['end']}"
        value = str(Decimal(str(fact["val"])) / Decimal(1_000_000))
        content = (
            f"{label}: {value} USD million; period {period}; filed {fact['filed']}; "
            f"form {fact['form']}; XBRL tag {fact['tag']}. "
            "Purchase-tag cash amount; company-defined NET capex may differ after sales/incentives. Excludes non-cash financing/leases."
            if metric == "capex"
            else f"{label}: {value} USD million; period {period}; filed {fact['filed']}; form {fact['form']}; XBRL tag {fact['tag']}."
        )
        out.append(
            Evidence(
                id=key,
                kind="financial",
                title=f"{label} · {fact['end']}",
                url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}/{accn}-index.html",
                filed=fact["filed"],
                accession=accn,
                sha256=digest,
                content=content,
                data={
                    **fact,
                    "cik": cik,
                    "metric": metric,
                    "unit": "USD",
                    "value": str(fact["val"]),
                    "frequency": frequency,
                },
            )
        )
    return out


def calculate(left: Evidence, right: Evidence, operation: str) -> Evidence:
    def basis(source):
        if source.kind == "financial":
            return source.data
        if source.kind == "calculation" and source.data.get("basis"):
            return source.data["basis"]
        raise ValueError("Calculations require financial facts or derived monetary amounts")

    a, b = basis(left), basis(right)
    if a["cik"] != b["cik"]:
        raise ValueError("Companies must match")
    if a["unit"] != b["unit"]:
        raise ValueError("Units must match")
    same_period = (a.get("start"), a["end"]) == (b.get("start"), b["end"])
    x, y = Decimal(a["value"]), Decimal(b["value"])
    if operation == "growth_pct":
        if (
            a["metric"] != b["metric"]
            or a["end"] <= b["end"]
            or a.get("frequency") != b.get("frequency")
        ):
            raise ValueError("Growth requires the same metric/frequency and a later left period")
        if bool(a.get("start")) != bool(b.get("start")):
            raise ValueError("Cannot compare instant and duration facts")
        if a.get("start"):
            spans = [
                (date.fromisoformat(v["end"]) - date.fromisoformat(v["start"])).days for v in (a, b)
            ]
            if abs(spans[0] - spans[1]) > 15:
                raise ValueError("Reporting durations are not comparable")
        if y <= 0:
            raise ValueError("Percentage growth from zero/negative baseline is not meaningful")
        result, unit, formula = (x / y - 1) * 100, "%", "(left / right - 1) * 100"
    elif operation == "ratio_pct":
        if not same_period or y == 0:
            raise ValueError("Ratios require identical reporting periods and a nonzero denominator")
        result, unit, formula = x / y * 100, "%", "(left / right) * 100"
    elif operation in ("difference", "sum"):
        if not same_period:
            raise ValueError(
                "Sum/difference requires identical reporting periods (e.g. OCF minus cash capex)"
            )
        result, unit, formula = (
            (x - y if operation == "difference" else x + y) / Decimal(1_000_000),
            "USD million",
            f"(left {'-' if operation == 'difference' else '+'} right) / 1000000",
        )
    else:
        raise ValueError("Unknown operation")
    value = str(result.quantize(Decimal("0.01")))
    key = "C" + hashlib.sha256(f"{left.id}:{right.id}:{operation}".encode()).hexdigest()[:14]
    content = (
        f"{operation}: {value} {unit}; formula {formula}; "
        f"left [{left.id}]: {a['metric']} = {x / Decimal(1_000_000)} USD million, period {a.get('start') or 'instant'} to {a['end']}; "
        f"right [{right.id}]: {b['metric']} = {y / Decimal(1_000_000)} USD million, period {b.get('start') or 'instant'} to {b['end']}. "
        "See input sources for original facts and prior calculation steps."
    )
    left_title = f"({left.title})" if left.kind == "calculation" else left.title
    right_title = f"({right.title})" if right.kind == "calculation" else right.title
    title = (
        f"Growth · {left_title} vs {right_title}"
        if operation == "growth_pct"
        else f"{left_title} / {right_title}"
        if operation == "ratio_pct"
        else f"{left_title} {'+' if operation == 'sum' else '−'} {right_title}"
    )
    return Evidence(
        id=key,
        kind="calculation",
        title=title,
        url=left.url,
        filed=max(left.filed, right.filed),
        content=content,
        inputs=[left.id, right.id],
        data={
            "result": value,
            "unit": unit,
            "formula": formula,
            "left": left.id,
            "right": right.id,
            **(
                {
                    "basis": {
                        "metric": f"{operation}({a['metric']},{b['metric']})",
                        "unit": "USD",
                        "value": str(x - y if operation == "difference" else x + y),
                        "start": a.get("start"),
                        "end": a["end"],
                        "frequency": a.get("frequency"),
                        "cik": a["cik"],
                    }
                }
                if operation in ("difference", "sum")
                else {}
            ),
        },
    )


def standard_comparisons(sources: dict[str, Evidence]) -> list[Evidence]:
    """Give the researcher baseline comparisons without asking it to do arithmetic.

    Only already-retrieved annual facts are used, and incompatible periods are
    omitted. No absent metric is silently fetched or estimated.
    """
    grouped = {}
    for source in sources.values():
        if source.kind == "financial" and source.data["frequency"] == "annual":
            grouped.setdefault(source.data["metric"], []).append(source)
    for rows in grouped.values():
        rows.sort(key=lambda row: row.data["end"], reverse=True)
    results = []
    for rows in grouped.values():
        if len(rows) >= 2:
            with contextlib.suppress(ValueError):
                results.append(calculate(rows[0], rows[1], "growth_pct"))
    for left_metric, right_metric, operation in [
        ("operating_cash_flow", "capex", "difference"),
        ("capex", "operating_cash_flow", "ratio_pct"),
        ("capex", "revenue", "ratio_pct"),
    ]:
        left_rows = grouped.get(left_metric, [])[:2]
        right_rows = grouped.get(right_metric, [])
        for left in left_rows:
            right = next(
                (
                    row
                    for row in right_rows
                    if (row.data.get("start"), row.data["end"])
                    == (left.data.get("start"), left.data["end"])
                ),
                None,
            )
            if right is not None:
                with contextlib.suppress(ValueError):
                    results.append(calculate(left, right, operation))
    for ocf in grouped.get("operating_cash_flow", [])[:2]:
        period = (ocf.data.get("start"), ocf.data["end"])
        items = [
            next(
                (
                    row
                    for row in grouped.get(metric, [])
                    if (row.data.get("start"), row.data["end"]) == period
                ),
                None,
            )
            for metric in ("capex", "repurchases", "dividends")
        ]
        if all(item is not None for item in items):
            capex, repurchases, dividends = items
            with contextlib.suppress(ValueError):
                fcf = calculate(ocf, capex, "difference")
                returns = calculate(repurchases, dividends, "sum")
                results.extend([fcf, returns, calculate(fcf, returns, "difference")])
    return results
