from __future__ import annotations

from html import escape
from typing import Sequence

from eneo.flows.runtime.document_rendering.blocks import (
    MAX_HEADING_LEVEL,
    DocumentBlock,
    InlineRuns,
    InlineTextRun,
)


def blocks_to_html_document(
    blocks: Sequence[DocumentBlock],
    *,
    title: str,
    language: str = "sv",
) -> str:
    body = "\n".join(_block_to_html(block) for block in blocks)
    return "\n".join(
        (
            "<!doctype html>",
            f'<html lang="{escape(language, quote=True)}">',
            "<head>",
            '<meta charset="utf-8">',
            f"<title>{escape(title)}</title>",
            "</head>",
            "<body>",
            '<main class="document">',
            body,
            "</main>",
            "</body>",
            "</html>",
        )
    )


def _block_to_html(block: DocumentBlock) -> str:
    if block.kind == "empty":
        return '<div class="block-spacer" aria-hidden="true"></div>'
    if block.kind == "heading":
        level = min(max(block.level or 1, 1), MAX_HEADING_LEVEL)
        return f"<h{level}>{_runs_html(block.runs, fallback=block.text)}</h{level}>"
    if block.kind == "bullet_list":
        return _list_to_html("ul", block)
    if block.kind == "numbered_list":
        return _list_to_html("ol", block)
    if block.kind == "code":
        return f"<pre><code>{escape(block.text)}</code></pre>"
    if block.kind == "table":
        return _table_to_html(block.rows, block.row_runs)
    return f"<p>{_runs_html(block.runs, fallback=block.text)}</p>"


def _list_to_html(tag: str, block: DocumentBlock) -> str:
    """Emit nested lists from the flat item/level pairs.

    A deeper item opens a sublist inside the previous item and closing tags
    follow the depth back down, so the HTML stays well formed for the PDF
    renderer and for assistive technology.
    """

    if not block.items:
        return ""
    start_attribute = (
        f' start="{block.start}"' if tag == "ol" and block.start != 1 else ""
    )
    parts: list[str] = [f"<{tag}{start_attribute}>"]
    depth = 0
    open_item = False
    for index, item in enumerate(block.items):
        level = block.item_level(index)
        while level > depth:
            parts.append(f"<{tag}>")
            depth += 1
            open_item = False
        while level < depth:
            if open_item:
                parts.append("</li>")
            parts.append(f"</{tag}>")
            depth -= 1
            open_item = True
        if open_item:
            parts.append("</li>")
        parts.append(
            f"<li>{_runs_html(_runs_at(block.item_runs, index), fallback=item)}"
        )
        open_item = True
    while depth > 0:
        if open_item:
            parts.append("</li>")
        parts.append(f"</{tag}>")
        depth -= 1
        open_item = True
    if open_item:
        parts.append("</li>")
    parts.append(f"</{tag}>")
    return "\n".join(parts)


def _table_to_html(
    rows: tuple[tuple[str, ...], ...],
    row_runs: tuple[tuple[InlineRuns, ...], ...],
) -> str:
    if not rows:
        return ""
    column_count = max(len(row) for row in rows)
    header = _row_to_html(
        "th",
        _normalized_row(rows[0], column_count),
        _normalized_run_row(_row_runs_at(row_runs, 0), column_count),
    )
    body_rows = "\n".join(
        _row_to_html(
            "td",
            _normalized_row(row, column_count),
            _normalized_run_row(_row_runs_at(row_runs, index), column_count),
        )
        for index, row in enumerate(rows[1:], start=1)
    )
    if not body_rows:
        return f"<table>\n<thead>\n{header}\n</thead>\n</table>"
    return (
        "<table>\n"
        "<thead>\n"
        f"{header}\n"
        "</thead>\n"
        "<tbody>\n"
        f"{body_rows}\n"
        "</tbody>\n"
        "</table>"
    )


def _row_to_html(
    cell_tag: str,
    row: tuple[str, ...],
    row_runs: tuple[InlineRuns, ...],
) -> str:
    cell_fragments: list[str] = []
    for index, cell in enumerate(row):
        content = _runs_html(_runs_at(row_runs, index), fallback=cell)
        attributes = ' scope="col"' if cell_tag == "th" else ""
        cell_fragments.append(f"<{cell_tag}{attributes}>{content}</{cell_tag}>")
    cells = "".join(cell_fragments)
    return f"<tr>{cells}</tr>"


def _normalized_row(row: tuple[str, ...], column_count: int) -> tuple[str, ...]:
    if len(row) >= column_count:
        return row
    return row + ("",) * (column_count - len(row))


def _normalized_run_row(
    row_runs: tuple[InlineRuns, ...],
    column_count: int,
) -> tuple[InlineRuns, ...]:
    if len(row_runs) >= column_count:
        return row_runs
    return row_runs + ((),) * (column_count - len(row_runs))


def _row_runs_at(
    rows: tuple[tuple[InlineRuns, ...], ...],
    index: int,
) -> tuple[InlineRuns, ...]:
    return rows[index] if index < len(rows) else ()


def _runs_at(runs: tuple[InlineRuns, ...], index: int) -> InlineRuns:
    return runs[index] if index < len(runs) else ()


def _runs_html(runs: InlineRuns, *, fallback: str) -> str:
    if not runs:
        return _inline_html(fallback)
    return "".join(_run_html(run) for run in runs)


def _run_html(run: InlineTextRun) -> str:
    text = _inline_html(run.text)
    if run.code:
        text = f"<code>{text}</code>"
    if run.bold:
        text = f"<strong>{text}</strong>"
    if run.italic:
        text = f"<em>{text}</em>"
    if run.strikethrough:
        text = f"<s>{text}</s>"
    if run.href:
        text = f'<a href="{escape(run.href, quote=True)}">{text}</a>'
    return text


def _inline_html(text: str) -> str:
    return "<br>".join(escape(line) for line in text.split("\n"))
