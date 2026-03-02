"""PDF and DOCX generation for flow step outputs."""
from __future__ import annotations

import os

from intric.main.exceptions import TypedIOValidationException

_DEJAVU_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


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
    for paragraph in text.split("\n\n"):
        doc.add_paragraph(paragraph)
    buf = io.BytesIO()
    doc.save(buf)
    return (
        buf.getvalue(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        f"step_{step_order}_output.docx",
    )
