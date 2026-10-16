"""Deterministic predicates. No model can modify a confirmed contract."""

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from quantcouncil.deep_research.finance import calculate
from quantcouncil.thesis_tracking.schemas import Rule, Snapshot

EVALUATOR_VERSION = "thesis-v3"


def contract_hash(statement: str, rule: dict | None, horizon: str, origin: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "statement": statement,
                "rule": rule,
                "horizon": horizon,
                "origin": origin,
                "evaluator": EVALUATOR_VERSION,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


class Incomparable(ValueError):
    pass


def evaluate(rule: Rule, snapshot: Snapshot, locked_roster: list[str] | None = None) -> dict:
    evidence = {s.id: s for s in snapshot.sources}
    used = set()
    checks = []

    def track(source):
        if source.filed > str(snapshot.as_of) or source.data.get("end", str(snapshot.as_of)) > str(
            snapshot.as_of
        ):
            raise Incomparable("Future evidence cannot enter a historical review")
        evidence[source.id] = source
        used.add(source.id)
        return source

    def calc(left, right, op):
        track(left)
        track(right)
        return track(calculate(left, right, op))

    def rows(metric, segment="consolidated"):
        return [
            s
            for s in snapshot.sources
            if s.data.get("metric_name") == metric and s.data.get("segment") == segment
        ]

    def value(source):
        return Decimal(source.data.get("basis", source.data)["value"])

    def at(metric, start, end, segment="consolidated"):
        matches = [
            s for s in rows(metric, segment) if (s.data["start"], s.data["end"]) == (start, end)
        ]
        if not matches:
            raise Incomparable(f"Missing {metric}/{segment} for {start} to {end}")
        return track(max(matches, key=lambda s: (s.filed, s.accession or "")))

    def monetary(metric, start, end):
        if metric == "free_cash_flow":
            return calc(
                at("operating_cash_flow", start, end), at("capex", start, end), "difference"
            )
        return at(metric, start, end)

    def period_pairs(metric, segment="consolidated"):
        selected = rows(metric, segment)
        observed_ends = {
            f["period"]
            for f in snapshot.manifest
            if rule.period != "annual" or f["form"].startswith("10-K")
        }
        periods = {}
        for s in selected:
            d = s.data
            span = (date.fromisoformat(d["end"]) - date.fromisoformat(d["start"])).days
            annual = d["form"].startswith("10-K") and 330 <= span <= 400
            # Every lane uses its own as-reported duration; never Q TTM as annual.
            current_filing_period = d["end"] in observed_ends
            if not current_filing_period or (rule.period == "annual" and not annual):
                continue
            if d["form"].startswith("10-Q") and span >= 330:
                continue
            key = d["end"]
            prior = periods.get(key)
            if prior is None or (span, s.filed) > (prior[0], prior[1].filed):
                periods[key] = (span, s)
        pairs = []
        for _, current in sorted(periods.values(), key=lambda v: v[1].data["end"], reverse=True):
            a = current.data
            end = date.fromisoformat(a["end"])
            span = (end - date.fromisoformat(a["start"])).days
            previous = [
                p
                for p in selected
                if 350 <= (end - date.fromisoformat(p.data["end"])).days <= 380
                and abs(
                    span
                    - (date.fromisoformat(p.data["end"]) - date.fromisoformat(p.data["start"])).days
                )
                <= 15
                and (rule.period != "annual" or p.data["form"].startswith("10-K"))
            ]
            pairs.append(
                (
                    current,
                    max(previous, key=lambda p: (p.filed, p.accession or "")) if previous else None,
                )
            )
        return pairs

    try:
        anchor = (
            "operating_income"
            if rule.template == "relative" or rule.metric == "operating_margin"
            else "operating_cash_flow"
            if rule.template == "coverage" or rule.metric == "free_cash_flow"
            else rule.metric
        )
        pairs = period_pairs(anchor)
        if not pairs:
            raise Incomparable("No eligible current as-reported period")
        n = rule.observations if rule.template == "trend" else 1
        expected_ends = sorted(
            {
                f["period"]
                for f in snapshot.manifest
                if f["period"] and (rule.period != "annual" or f["form"].startswith("10-K"))
            },
            reverse=True,
        )[:n]
        if [current.data["end"] for current, _ in pairs[:n]] != expected_ends:
            raise Incomparable(
                "Latest required disclosure is missing the confirmed metric; no older-period substitution"
            )
        if len(pairs) < n:
            raise Incomparable(
                "Not enough distinct disclosure periods for the confirmed trend window"
            )
        roster = None
        for current, prior in pairs[:n]:
            start, end = current.data["start"], current.data["end"]
            track(current)
            if rule.template in ("trend", "relative") and prior is None:
                raise Incomparable("Prior-year comparable period is missing")
            if rule.template == "coverage":
                ocf = at("operating_cash_flow", start, end)
                expenses = [at(m, start, end) for m in rule.cash_outflows]
                if any(value(expense) < 0 for expense in expenses):
                    raise Incomparable(
                        "Negative cash expense requires a different explicit metric definition"
                    )
                total = expenses[0]
                for expense in expenses[1:]:
                    total = calc(total, expense, "sum")
                residual = calc(ocf, total, "difference")
                passed = (
                    value(residual) >= 0
                    if rule.coverage_expectation == "covers"
                    else value(residual) < 0
                )
                detail = {
                    "expectation": rule.coverage_expectation,
                    "ocf_usd": str(value(ocf)),
                    "cash_outflows_usd": str(value(total)),
                    "residual_usd": str(value(residual)),
                }
            elif rule.template == "relative":
                old_start, old_end = prior.data["start"], prior.data["end"]

                def members(a, b):
                    return {
                        s.data["segment"]
                        for s in snapshot.sources
                        if s.data.get("metric_name") == "operating_income"
                        and s.data.get("segment") != "consolidated"
                        and (s.data["start"], s.data["end"]) == (a, b)
                    }

                roster = sorted(members(start, end))
                if (
                    len(roster) < 2
                    or set(roster) != members(old_start, old_end)
                    or (locked_roster is not None and roster != sorted(locked_roster))
                ):
                    raise Incomparable(
                        "Segment membership is missing or changed; no silent remapping"
                    )
                if rule.target_segment not in roster:
                    raise Incomparable("The confirmed target segment is unavailable")
                # A reconciled roster is necessary, not sufficient: meaning/scope review
                # also has to establish exhaustive reportable-segment coverage.
                for a, b in [(start, end), (old_start, old_end)]:
                    if abs(
                        sum(value(at("operating_income", a, b, member)) for member in roster)
                        - value(at("operating_income", a, b))
                    ) > Decimal(1000000):
                        raise Incomparable(
                            "Segment totals do not reconcile to group operating income"
                        )
                group = calc(current, prior, "change")
                changes = {
                    member: calc(
                        at("operating_income", start, end, member),
                        at("operating_income", old_start, old_end, member),
                        "change",
                    )
                    for member in roster
                }
                target = changes[rule.target_segment]
                passed = (
                    value(group) > 0
                    and value(target) > 0
                    and all(
                        value(target) > value(v)
                        for k, v in changes.items()
                        if k != rule.target_segment
                    )
                )
                detail = {
                    "group_change_usd": str(value(group)),
                    "segment_changes_usd": {m: str(value(v)) for m, v in changes.items()},
                    "definition": "unique largest positive individual contributor; NOT majority share",
                }
                if value(group) > 0:
                    detail["contribution_pct"] = calc(target, group, "ratio_pct").data["result"]
            else:
                if rule.metric == "operating_margin":

                    def margin(a, b):
                        revenue = at("revenue", a, b)
                        if value(revenue) <= 0:
                            raise Incomparable("Operating margin requires positive revenue")
                        numerator = at("operating_income", a, b)
                        result = calc(numerator, revenue, "ratio_pct")
                        result.data["unrounded_result"] = str(
                            value(numerator) / value(revenue) * 100
                        )
                        result.content += (
                            f" Exact unrounded result: {result.data['unrounded_result']} %."
                        )
                        return result

                    amount = margin(start, end)
                    number = Decimal(amount.data["unrounded_result"])
                else:
                    amount = monetary(rule.metric, start, end)
                    number = value(amount) / Decimal(1000000)
                if rule.template == "trend":
                    a, b = prior.data["start"], prior.data["end"]
                    earlier = (
                        margin(a, b)
                        if rule.metric == "operating_margin"
                        else monetary(rule.metric, a, b)
                    )
                    old = (
                        Decimal(earlier.data["unrounded_result"])
                        if rule.metric == "operating_margin"
                        else value(earlier) / Decimal(1000000)
                    )
                    passed = number > old
                    detail = {
                        "current": str(number),
                        "previous": str(old),
                        "basis": "strict year-on-year increase in levels, not percentage growth from a negative base",
                    }
                else:
                    passed = {
                        "gt": number > rule.threshold,
                        "gte": number >= rule.threshold,
                        "lt": number < rule.threshold,
                        "lte": number <= rule.threshold,
                    }[rule.operator]
                    detail = {
                        "current": str(number),
                        "threshold": str(rule.threshold),
                        "operator": rule.operator,
                    }
                detail["unit"] = "%" if rule.metric == "operating_margin" else "USD million"
            checks.append({"start": start, "end": end, "passed": bool(passed), **detail})
        result = "supported" if all(c["passed"] for c in checks) else "contradicted"
        reason = (
            "All confirmed numerical conditions hold"
            if result == "supported"
            else "At least one confirmed numerical condition fails; no trading conclusion is implied"
        )
        eligible = True
    except (Incomparable, ValueError, KeyError) as exc:
        result, reason, eligible = "insufficient", str(exc), False
        roster = None
    return {
        "judgment": result,
        "reason": reason,
        "eligible": eligible,
        "checks": checks,
        "segment_roster": roster,
        "sources": [evidence[k].model_dump(mode="json") for k in sorted(used)],
        "evaluator_version": EVALUATOR_VERSION,
        "evaluator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
