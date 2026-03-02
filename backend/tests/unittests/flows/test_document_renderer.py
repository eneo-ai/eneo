"""Tests for intric.flows.runtime.document_renderer — PDF/DOCX generation."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from intric.flows.runtime.document_renderer import render_document
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


# --- DOCX rendering ---


def test_render_docx_valid_blob():
    blob, mimetype, filename = render_document("Hello world", "docx", step_order=1)
    assert isinstance(blob, bytes)
    assert len(blob) > 0
    # DOCX is a ZIP file — starts with PK magic bytes
    assert blob[:2] == b"PK"


def test_render_docx_correct_mime():
    _, mimetype, _ = render_document("Test", "docx", step_order=1)
    assert mimetype == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_render_docx_filename_pattern():
    _, _, filename = render_document("Test", "docx", step_order=5)
    assert filename == "step_5_output.docx"


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
    """When DejaVu font is not installed, Helvetica fallback renders ASCII."""
    with patch("intric.flows.runtime.document_renderer.os.path.exists", return_value=False):
        blob, _, _ = render_document("ASCII only text", "pdf", step_order=1)
    assert isinstance(blob, bytes)
    assert blob[:5] == b"%PDF-"
