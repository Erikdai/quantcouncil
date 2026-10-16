"""Code checks may tighten a model's semantic classification, never relax it."""

import re

from quantcouncil.thesis_tracking.schemas import Rule

YEAR = re.compile(
    r"(?<!\d)(?:19|20)\d{2}(?:\s*(?:财年|年度|全年|年)|-\d{2}-\d{2})|\b(?:FY|fiscal year|year ended)\s*(?:19|20)\d{2}\b",
    re.I,
)


def guard_meaning(origin: dict, statement: str, rule: Rule, review: dict) -> dict:
    checked = {
        **review,
        "model_relationship": review["relationship"],
        "issues": list(review["issues"]),
        "assumptions": list(review["assumptions"]),
        "code_checks": [],
    }
    if YEAR.search(statement):
        checked["rule_matches_statement"] = False
        checked["issues"].append(
            "拟追踪观点含固定历史年份，但当前模板随最新披露滚动；请将年份留在基准证据中，明确改写持续检验的假设，或仅保存历史事实。"
        )
        checked["code_checks"].append("fixed_year_cannot_bind_a_rolling_rule")
    elif YEAR.search(origin["original_text"]):
        if checked["relationship"] == "direct":
            checked["relationship"] = "new_hypothesis"
        checked["assumptions"].append(
            "原文包含固定历史期间；持续复查是新假设，不能当作原报告已作出的预测。"
        )
        checked["code_checks"].append("historical_to_rolling_requires_explicit_reformulation")
    if rule.template == "trend" and rule.observations > 1:
        explicit = {
            2: r"(?:连续|最近|过去|last|consecutive)\s*(?:2|二|两|two)",
            3: r"(?:连续|最近|过去|last|consecutive)\s*(?:3|三|three)",
        }
        if not re.search(explicit[rule.observations], origin["original_text"], re.I):
            checked["assumptions"].append(
                f"连续{rule.observations}次披露的观察窗口是新设定，原文未明确这一窗口。"
            )
            checked["code_checks"].append("added_observation_window")
    checked["assumptions"] = list(dict.fromkeys(checked["assumptions"]))
    return checked
