"""A small, format-neutral document model, and Markdown-to-blocks conversion."""

from __future__ import annotations

from dataclasses import dataclass, field

from markdown_it import MarkdownIt

Run = tuple[str, bool]  # (text, bold)


@dataclass
class Heading:
    text: str
    level: int = 1


@dataclass
class Para:
    runs: list[Run]
    muted: bool = False


@dataclass
class Bullets:
    items: list[list[Run]]


@dataclass
class Table:
    header: list[str]
    rows: list[list[str]]


@dataclass
class Report:
    title: str
    subtitle: str
    blocks: list = field(default_factory=list)


def text(value: str, bold: bool = False) -> Para:
    return Para([(value, bold)])


_md = MarkdownIt("commonmark").enable("table")
ESCAPED_NEWLINE = "\\n"  # a backslash and an "n", as some structured outputs leave them


def _inline(token) -> list[Run]:
    runs: list[Run] = []
    bold = False
    for child in token.children or []:
        if child.type == "strong_open":
            bold = True
        elif child.type == "strong_close":
            bold = False
        elif child.type in ("text", "code_inline") and child.content:
            runs.append((child.content, bold))
        elif child.type in ("softbreak", "hardbreak"):
            runs.append((" " if child.type == "softbreak" else "\n", bold))
    return runs or [("", False)]


def _plain(token) -> str:
    return "".join(t for t, _ in _inline(token)).strip()


def markdown_blocks(source: str, heading_offset: int = 1) -> list:
    """Headings, paragraphs, (flattened) lists and tables from agent Markdown."""
    # Structured-output decisions sometimes carry escaped newlines as literal text.
    tokens = _md.parse((source or "").replace(ESCAPED_NEWLINE, "\n"))
    blocks: list = []
    list_depth, items = 0, []
    row: list[str] = []
    table: Table | None = None
    for i, tok in enumerate(tokens):
        if tok.type == "heading_open":
            level = min(int(tok.tag[1]) + heading_offset, 4)
            blocks.append(Heading(_plain(tokens[i + 1]), level))
        elif tok.type in ("bullet_list_open", "ordered_list_open"):
            list_depth += 1
        elif tok.type in ("bullet_list_close", "ordered_list_close"):
            list_depth -= 1
            if list_depth == 0 and items:
                blocks.append(Bullets(items))
                items = []
        elif tok.type == "inline" and list_depth and tokens[i - 1].type == "paragraph_open":
            runs = _inline(tok)
            items.append(runs if list_depth == 1 else [("  " * (list_depth - 1), False), *runs])
        elif tok.type == "inline" and tokens[i - 1].type == "paragraph_open" and not table:
            blocks.append(Para(_inline(tok)))
        elif tok.type == "table_open":
            table = Table(header=[], rows=[])
        elif tok.type == "tr_open":
            row = []
        elif tok.type == "inline" and table is not None and tokens[i - 1].type in ("th_open", "td_open"):
            row.append(_plain(tok))
        elif tok.type == "tr_close" and table is not None:
            if not table.header:
                table.header = row
            else:
                table.rows.append(row)
        elif tok.type == "table_close" and table is not None:
            blocks.append(table)
            table = None
        elif tok.type in ("fence", "code_block"):
            blocks.append(Para([(tok.content.rstrip(), False)], muted=True))
    return blocks
