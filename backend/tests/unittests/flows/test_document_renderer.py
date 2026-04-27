"""Tests for intric.flows.runtime.document_renderer — PDF/DOCX generation."""

from __future__ import annotations

import io
from unittest.mock import patch

import pdfplumber
import pytest
from docx import Document

from intric.flows.runtime import document_renderer as document_renderer_module
from intric.flows.runtime.document_renderer import (
    render_document,
    render_structured_document,
)
from intric.main.exceptions import TypedIOValidationException

# --- PDF rendering ---


def test_render_pdf_valid_blob():
    blob, mimetype, filename = render_document("Hello world", "pdf", step_order=1)
    assert isinstance(blob, bytes)
    assert len(blob) > 0
    assert blob[:5] == b"%PDF-"


def test_render_pdf_correct_mime():
    _, mimetype, _ = render_document("Test", "pdf", step_order=1)
    assert mimetype == "application/pdf"


def test_render_pdf_filename_pattern():
    _, _, filename = render_document("Test", "pdf", step_order=3)
    assert filename == "step_3_output.pdf"


def test_render_pdf_markdown_headings_and_lists_as_readable_document():
    text = "# Titel\n\n## Sammanfattning\n\n- punkt ett\n- punkt två\n\n1. nästa steg"

    blob, _, _ = render_document(text, "pdf", step_order=1)

    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        page_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "Titel" in page_text
    assert "Sammanfattning" in page_text
    assert "punkt ett" in page_text
    assert "# Titel" not in page_text
    assert "## Sammanfattning" not in page_text


def test_render_pdf_markdown_table_outputs_cells_without_separator_row():
    text = "| Namn | Värde |\n| --- | --- |\n| Kommun | Sundsvall |"

    blob, _, _ = render_document(text, "pdf", step_order=1)

    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        page_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "Namn" in page_text
    assert "Sundsvall" in page_text
    assert "---" not in page_text


# --- DOCX rendering ---


def test_render_docx_valid_blob():
    blob, mimetype, filename = render_document("Hello world", "docx", step_order=1)
    assert isinstance(blob, bytes)
    assert len(blob) > 0
    # DOCX is a ZIP file — starts with PK magic bytes
    assert blob[:2] == b"PK"


def test_render_docx_correct_mime():
    _, mimetype, _ = render_document("Test", "docx", step_order=1)
    assert (
        mimetype
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


def test_render_docx_filename_pattern():
    _, _, filename = render_document("Test", "docx", step_order=5)
    assert filename == "step_5_output.docx"


def test_render_docx_empty_output_still_valid():
    """Empty markdown should still produce a readable DOCX file."""
    blob, _, _ = render_document("", "docx", step_order=1)
    doc = Document(io.BytesIO(blob))
    assert isinstance(blob, bytes)
    assert len(doc.paragraphs) >= 1


def test_render_docx_preserves_swedish_characters():
    """Swedish characters should survive DOCX rendering."""
    text = "Svenska tecken: å ä ö"
    blob, _, _ = render_document(text, "docx", step_order=1)
    doc = Document(io.BytesIO(blob))
    all_text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    assert "å" in all_text
    assert "ä" in all_text
    assert "ö" in all_text


def test_render_docx_markdown_table_creates_table():
    """Markdown table syntax should become a DOCX table."""
    text = "| Namn | Värde |\n| --- | --- |\n| Kommun | Sundsvall |"
    blob, _, _ = render_document(text, "docx", step_order=1)
    doc = Document(io.BytesIO(blob))
    assert len(doc.tables) == 1
    assert doc.tables[0].cell(0, 0).text == "Namn"
    assert doc.tables[0].cell(1, 1).text == "Sundsvall"


def test_render_structured_docx_uses_schema_titles_and_tables():
    """Validated JSON contracts should render as semantic DOCX content."""
    blob, _, _ = render_structured_document(
        {
            "summary": "Kort sammanfattning",
            "actions": [
                {"task": "Läsa mer", "owner": "Leona"},
                {"owner": "Lärare", "task": "Följa upp"},
            ],
        },
        "docx",
        step_order=1,
        schema={
            "title": "Utvecklingsrapport",
            "type": "object",
            "properties": {
                "summary": {"title": "Sammanfattning", "type": "string"},
                "actions": {
                    "title": "Åtgärder",
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "owner": {"title": "Ansvarig", "type": "string"},
                            "task": {"title": "Uppgift", "type": "string"},
                        },
                    },
                },
            },
        },
    )

    doc = Document(io.BytesIO(blob))
    all_text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    assert "Utvecklingsrapport" in all_text
    assert "Sammanfattning" in all_text
    assert "Kort sammanfattning" in all_text
    assert len(doc.tables) == 1
    assert doc.tables[0].cell(0, 0).text == "Ansvarig"
    assert doc.tables[0].cell(0, 1).text == "Uppgift"
    assert doc.tables[0].cell(1, 1).text == "Läsa mer"


def test_render_structured_docx_pins_null_and_empty_array_values():
    """Missing structured values should stay visible instead of disappearing."""
    blob, _, _ = render_structured_document(
        {"summary": None, "notes": []},
        "docx",
        step_order=1,
        schema={
            "type": "object",
            "properties": {
                "summary": {"title": "Sammanfattning", "type": "string"},
                "notes": {"title": "Anteckningar", "type": "array"},
            },
        },
    )

    doc = Document(io.BytesIO(blob))
    all_text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    assert "Sammanfattning: -" in all_text
    assert "Anteckningar" in all_text
    assert "-" in all_text


def test_render_structured_docx_escapes_scalar_markdown_control_text():
    """JSON strings are data and must not become document structure."""
    blob, _, _ = render_structured_document(
        {"summary": "Rad ett\n# Inte en rubrik\n```inte kod```"},
        "docx",
        step_order=1,
        schema={
            "type": "object",
            "properties": {
                "summary": {"title": "Sammanfattning", "type": "string"},
            },
        },
    )

    doc = Document(io.BytesIO(blob))
    paragraph_texts = [paragraph.text for paragraph in doc.paragraphs]
    assert (
        "Sammanfattning: Rad ett\n# Inte en rubrik\n'''inte kod'''" in paragraph_texts
    )
    assert "Inte en rubrik" not in paragraph_texts


def test_render_structured_docx_table_cells_preserve_pipe_characters():
    """Escaped Markdown table pipes should round-trip into DOCX table cells."""
    blob, _, _ = render_structured_document(
        {"rows": [{"name": "A | B", "value": "C"}]},
        "docx",
        step_order=1,
        schema={"type": "object", "properties": {"rows": {"type": "array"}}},
    )

    doc = Document(io.BytesIO(blob))
    assert len(doc.tables) == 1
    assert doc.tables[0].cell(1, 0).text == "A | B"


def test_render_structured_pdf_table_does_not_truncate_long_cell_values():
    """PDF fallback tables should prefer readable wrapping over lossy truncation."""
    long_value = (
        "Detaljerad uppföljning med tillräckligt många ord för att behöva "
        "radbrytas i PDF-tabellen och ändå behålla unique-tail-token."
    )

    blob, _, _ = render_structured_document(
        {"actions": [{"owner": "Leona", "task": long_value}]},
        "pdf",
        step_order=1,
        schema={"type": "object", "properties": {"actions": {"type": "array"}}},
    )

    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        page_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "unique-tail-token" in page_text


def test_render_structured_pdf_table_repeats_headers_after_page_break():
    rows = [
        {
            "owner": f"Person {index}",
            "task": (
                "Följ upp utvecklingsmål och dokumentera status med tillräcklig "
                f"detalj för radbrytning {index}."
            ),
        }
        for index in range(45)
    ]

    blob, _, _ = render_structured_document(
        {"actions": rows},
        "pdf",
        step_order=1,
        schema={
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "owner": {"title": "Ansvarig", "type": "string"},
                            "task": {"title": "Uppgift", "type": "string"},
                        },
                    },
                }
            },
        },
    )

    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        assert len(pdf.pages) > 1
        second_page_text = pdf.pages[1].extract_text() or ""
    assert "Ansvarig" in second_page_text
    assert "Uppgift" in second_page_text


def test_pdf_table_column_widths_follow_content_weight():
    class _FakePdf:
        def get_string_width(self, text: str) -> float:
            return float(len(text))

    widths = document_renderer_module._pdf_table_column_widths(
        pdf=_FakePdf(),
        rows=(
            ("Kort", "Lång beskrivning med mycket mer text"),
            ("A", "Ytterligare lång cell"),
        ),
        usable_width=120,
        max_columns=2,
    )

    assert sum(widths) == pytest.approx(120)
    assert widths[1] > widths[0]


def test_render_docx_markdown_lists_and_code_blocks():
    """Lists and fenced code blocks should be represented in DOCX text."""
    text = "# Titel\n\n- punkt ett\n- punkt två\n\n```python\nprint('hej')\n```"
    blob, _, _ = render_document(text, "docx", step_order=1)
    doc = Document(io.BytesIO(blob))
    all_text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    assert "Titel" in all_text
    assert "punkt ett" in all_text
    assert "print('hej')" in all_text


def test_render_docx_very_long_output():
    """Very long markdown output should produce a valid DOCX without exceptions."""
    text = ("Rad med innehåll och åäö.\n" * 5000).strip()
    blob, _, _ = render_document(text, "docx", step_order=1)
    doc = Document(io.BytesIO(blob))
    assert len(blob) > 0
    assert any("åäö" in paragraph.text for paragraph in doc.paragraphs)


def test_render_docx_still_works_when_package_default_template_is_missing():
    """Renderer should not depend on python-docx package template layout."""
    with patch("docx.api._default_docx_path", return_value="/tmp/missing-default.docx"):
        blob, _, _ = render_document("Fallback template test", "docx", step_order=1)
    doc = Document(io.BytesIO(blob))
    all_text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    assert "Fallback template test" in all_text


# --- Error handling ---


def test_render_unsupported_type_raises():
    with pytest.raises(TypedIOValidationException, match="Unsupported document type"):
        render_document("Test", "html", step_order=1)


def test_render_unsupported_error_code():
    with pytest.raises(TypedIOValidationException) as exc_info:
        render_document("Test", "html", step_order=1)
    assert exc_info.value.code == "typed_io_render_failed"


# --- Unicode rendering ---


def test_render_pdf_unicode_characters():
    """Em-dash, Swedish chars, curly quotes must render without error."""
    text = "Em-dash \u2014 and Swedish: \u00e5\u00e4\u00f6 and curly \u201cquotes\u201d"
    blob, mimetype, filename = render_document(text, "pdf", step_order=1)
    assert isinstance(blob, bytes)
    assert len(blob) > 0
    assert blob[:5] == b"%PDF-"


def test_render_pdf_font_fallback():
    """When no Unicode font is available, PDF rendering still degrades safely."""
    with patch(
        "intric.flows.runtime.document_renderer._resolved_pdf_unicode_font",
        return_value=None,
    ):
        blob, _, _ = render_document(
            "Em-dash \u2014 and curly \u201cquotes\u201d",
            "pdf",
            step_order=1,
        )
    assert isinstance(blob, bytes)
    assert blob[:5] == b"%PDF-"
