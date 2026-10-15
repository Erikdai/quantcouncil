"""Agent Skills (SKILL.md): agents see the index and load a playbook on demand."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from langchain_core.tools import tool

_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path

    @property
    def body(self) -> str:
        return _parse(self.path)[1]


def skills_dir() -> Path:
    env = os.getenv("QUANTCOUNCIL_SKILLS_DIR")
    candidates = [Path(env)] if env else []
    candidates += [Path.cwd() / "skills", Path(__file__).resolve().parents[2] / "skills"]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[-1]


def _parse(path: Path) -> tuple[dict[str, str], str]:
    raw = path.read_text(encoding="utf-8")
    m = _FRONT_MATTER.match(raw)
    if not m:
        return {}, raw
    meta: dict[str, str] = {}
    key = None
    for line in m.group(1).splitlines():
        if re.match(r"^[A-Za-z_][\w-]*:", line):
            key, _, value = line.partition(":")
            key = key.strip()
            meta[key] = value.strip().strip("\"'")
        elif key and line.startswith((" ", "\t")):  # folded continuation
            meta[key] = (meta[key] + " " + line.strip()).strip()
    return meta, m.group(2).strip()


@lru_cache(maxsize=1)
def _index(root: str) -> tuple[Skill, ...]:
    skills = []
    for skill_md in sorted(Path(root).glob("*/SKILL.md")):
        meta, _ = _parse(skill_md)
        name = meta.get("name") or skill_md.parent.name
        skills.append(Skill(name=name, description=meta.get("description", ""), path=skill_md))
    return tuple(skills)


def list_skills() -> list[Skill]:
    return list(_index(str(skills_dir())))


def get_skill(name: str) -> Skill | None:
    return next((s for s in list_skills() if s.name == name), None)


def skills_index_prompt() -> str:
    skills = list_skills()
    if not skills:
        return ""
    lines = "\n".join(f"- {s.name}: {s.description}" for s in skills)
    return ("You have these skills (domain playbooks). When a task matches one, call load_skill with its "
            f"name before answering, then follow it:\n{lines}")


@tool
def load_skill(name: str) -> str:
    """Load the full instructions of a skill by name (see the skill index in your instructions)."""
    skill = get_skill(name)
    if skill is None:
        return f"No skill named {name!r}. Available: {', '.join(s.name for s in list_skills())}"
    return skill.body
