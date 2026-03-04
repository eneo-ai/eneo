"""PDF and DOCX generation for flow step outputs."""
from __future__ import annotations

import os
import re
from typing import Any

from intric.main.exceptions import TypedIOValidationException

_DEJAVU_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_MARKDOWN_TABLE_SEPARATOR = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$"
)
_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$")
_BULLET_PATTERN = re.compile(r"^[-*]\s+(.+)$")
_NUMBERED_PATTERN = re.compile(r"^\d+\.\s+(.+)$")


def render_document(
    text: str, output_type: str, *, step_order: int
) -> tuple[bytes, str, str]:
    """Render text as PDF or DOCX. Returns (blob, mimetype, filename)."""
    renderers = {"pdf": _render_pdf, "docx": _render_docx}
    renderer = renderers.get(output_type)
    if renderer is None:
        raise TypedIOValidationException(
            f"Unsupported document type: {output_type}",
            code="typed_io_render_failed",
        )
    try:
        return renderer(text, step_order=step_order)
    except TypedIOValidationException:
        raise
    except Exception as exc:
        raise TypedIOValidationException(
            f"Document render failed: {exc}",
            code="typed_io_render_failed",
        ) from exc


def _render_pdf(text: str, *, step_order: int) -> tuple[bytes, str, str]:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    if os.path.exists(_DEJAVU_PATH):
        pdf.add_font("DejaVu", fname=_DEJAVU_PATH)
        pdf.set_font("DejaVu", size=11)
    else:
        pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, text)
    return bytes(pdf.output()), "application/pdf", f"step_{step_order}_output.pdf"


def _render_docx(text: str, *, step_order: int) -> tuple[bytes, str, str]:
    import io

    from docx import Document

    doc = Document()
    lines = text.splitlines()
    if not lines:
        doc.add_paragraph("")
    else:
        _write_markdown_blocks(doc=doc, lines=lines)
    buf = io.BytesIO()
    doc.save(buf)
    return (
        buf.getvalue(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        f"step_{step_order}_output.docx",
    )


def _write_markdown_blocks(*, doc: Any, lines: list[str]) -> None:
    index = 0
    in_code_block = False
    code_lines: list[str] = []

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code_block:
                _append_code_block(doc=doc, code_lines=code_lines)
                code_lines = []
                in_code_block = False
            else:
                in_code_block = True
            index += 1
            continue

        if in_code_block:
            code_lines.append(line.rstrip("\n"))
            index += 1
            continue

        next_index = _consume_markdown_table(doc=doc, lines=lines, start_index=index)
        if next_index is not None:
            index = next_index
            continue

        if stripped == "":
            # Keep spacing between markdown blocks.
            doc.add_paragraph("")
            index += 1
            continue

        heading_match = _HEADING_PATTERN.match(stripped)
        if heading_match:
            level = min(len(heading_match.group(1)), 4)
            doc.add_heading(heading_match.group(2).strip(), level=level)
            index += 1
            continue

        bullet_match = _BULLET_PATTERN.match(stripped)
        if bullet_match:
            doc.add_paragraph(bullet_match.group(1).strip(), style="List Bullet")
            index += 1
            continue

        numbered_match = _NUMBERED_PATTERN.match(stripped)
        if numbered_match:
            doc.add_paragraph(numbered_match.group(1).strip(), style="List Number")
            index += 1
            continue

        paragraph_lines = [line]
        index += 1
        while index < len(lines):
            candidate = lines[index]
            candidate_stripped = candidate.strip()
            if candidate_stripped == "":
                break
            if candidate_stripped.startswith("```"):
                break
            if _HEADING_PATTERN.match(candidate_stripped):
                break
            if _BULLET_PATTERN.match(candidate_stripped):
                break
            if _NUMBERED_PATTERN.match(candidate_stripped):
                break
            if _is_markdown_table_start(lines=lines, start_index=index):
                break
            paragraph_lines.append(candidate)
            index += 1
        doc.add_paragraph("\n".join(paragraph_lines).strip())

    if in_code_block:
        _append_code_block(doc=doc, code_lines=code_lines)


def _consume_markdown_table(
    *,
    doc: Any,
    lines: list[str],
    start_index: int,
) -> int | None:
    if not _is_markdown_table_start(lines=lines, start_index=start_index):
        return None

    header_cells = _parse_markdown_table_row(lines[start_index])
    if not header_cells:
        return None

    rows: list[list[str]] = [header_cells]
    index = start_index + 2  # Skip separator row.

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped == "" or "|" not in line:
            break
        cells = _parse_markdown_table_row(line)
        if not cells:
            break
        rows.append(cells)
        index += 1

    max_columns = max(len(row) for row in rows)
    table = doc.add_table(rows=len(rows), cols=max_columns)
    for row_idx, row in enumerate(rows):
        for col_idx in range(max_columns):
            value = row[col_idx] if col_idx < len(row) else ""
            table.cell(row_idx, col_idx).text = value
    return index


def _is_markdown_table_start(*, lines: list[str], start_index: int) -> bool:
    if start_index + 1 >= len(lines):
        return False
    header = lines[start_index]
    separator = lines[start_index + 1]
    return "|" in header and _MARKDOWN_TABLE_SEPARATOR.match(separator.strip()) is not None


def _parse_markdown_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped:
        return []
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _append_code_block(*, doc: Any, code_lines: list[str]) -> None:
    paragraph = doc.add_paragraph("\n".join(code_lines))
    if not paragraph.runs:
        return
    for run in paragraph.runs:
        run.font.name = "Courier New"
