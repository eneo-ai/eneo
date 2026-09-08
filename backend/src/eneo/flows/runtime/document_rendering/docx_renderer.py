from __future__ import annotations

from pathlib import Path
from typing import Sequence

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.runtime.document_rendering.blocks import DocumentBlock
from eneo.flows.runtime.document_rendering.docx_content_controls import (
    fill_rich_control,
    inspect_content_controls,
)
from eneo.flows.runtime.document_rendering.docx_writer import DocxBlockWriter
from eneo.flows.runtime.document_rendering.renderers import RenderedDocument
from eneo.main.exceptions import TypedIOValidationException

STANDARD_TEMPLATES_DIR = (
    Path(__file__).resolve().parent.parent / "templates" / "standard"
)
# The standard body template: house styles, language and page furniture with
# one rich text control that receives the whole document.
STANDARD_DOCUMENT_TEMPLATE_PATH = STANDARD_TEMPLATES_DIR / "dokument.docx"
DOCUMENT_BODY_CONTROL_TAG = "dokument"
_DOCX_MIMETYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


class DocxDocumentRenderer:
    output_type = "docx"

    def __init__(
        self, *, template_path: Path = STANDARD_DOCUMENT_TEMPLATE_PATH
    ) -> None:
        self._template_path = template_path

    def render(
        self,
        blocks: Sequence[DocumentBlock],
        *,
        step_order: int,
    ) -> RenderedDocument:
        import io

        from docx import Document

        document = Document(str(self._template_path))
        body_control = next(
            (
                control
                for control in inspect_content_controls(document)
                if control.kind == "rich" and control.name == DOCUMENT_BODY_CONTROL_TAG
            ),
            None,
        )
        if body_control is None:
            raise TypedIOValidationException(
                "The standard document template has no body control.",
                code=FlowApiErrorCode.TYPED_IO_RENDER_FAILED.value,
            )
        writer = DocxBlockWriter(document)
        fill_rich_control(
            body_control,
            writer.elements(blocks, heading_base=body_control.heading_level),
        )
        title = next(
            (block.text for block in blocks if block.kind == "heading" and block.text),
            None,
        )
        if title:
            document.core_properties.title = title
        buf = io.BytesIO()
        document.save(buf)
        return RenderedDocument(
            blob=buf.getvalue(),
            mimetype=_DOCX_MIMETYPE,
            filename=f"step_{step_order}_output.docx",
        )
