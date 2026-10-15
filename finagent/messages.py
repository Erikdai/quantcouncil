"""Helpers for LangChain message content across providers."""

from __future__ import annotations

from typing import Any


def content_text(content: Any) -> str:
    """Plain text of a message's content: a string (OpenAI-compatible) or a list of
    content blocks (Anthropic), where only ``text`` blocks are kept."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content
                       if not isinstance(b, dict) or b.get("type", "text") == "text")
    return ""
