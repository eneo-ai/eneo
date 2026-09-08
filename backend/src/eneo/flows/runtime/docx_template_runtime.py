"""DOCX template inspection, fill and text extraction.

Templates carry their fill targets as Word content controls (see
``docx_content_controls``). Inspection lists them, fill writes each bound
value into its control with the template's own styles, and extraction reads
the finished document through the same reader every uploaded DOCX goes
through, so control content is never invisible to the run's text output.
"""

from __future__ import annotations

import io
import logging
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from docx import Document
from docx2python import docx2python

from eneo.files.docx_template_validation import (
    normalize_template_extraction_error,
    validate_docx_template_archive,
)
from eneo.files.text import CorruptFileError
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.runtime.document_rendering.blocks import DocumentBlock
from eneo.flows.runtime.document_rendering.docx_content_controls import (
    ContentControl,
    ContentControlKind,
    DocxTemplateContractError,
    fill_rich_control,
    fill_text_control,
    inspect_content_controls,
    remove_control,
)
from eneo.flows.runtime.document_rendering.docx_writer import DocxBlockWriter
from eneo.flows.runtime.document_rendering.limits import (
    DEFAULT_DOCUMENT_RENDER_LIMITS,
    DocumentRenderLimits,
    ensure_blocks_within_limits,
    ensure_source_within_limits,
)
from eneo.flows.runtime.document_rendering.markdown_blocks import (
    parse_markdown_blocks,
)
from eneo.main.exceptions import TypedIOValidationException

logger = logging.getLogger(__name__)

_DOCX_MIMETYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_PREVIEW_CHARS = 2000


@dataclass(frozen=True, slots=True)
class TemplatePlaceholderSpec:
    """One fill target as callers outside the runtime see it."""

    name: str
    label: str
    kind: ContentControlKind
    hint: str | None
    location: str


def inspect_docx_template_placeholders(
    template_bytes: bytes,
    *,
    filename: str,
) -> tuple[TemplatePlaceholderSpec, ...]:
    """List the template's fill targets in document order."""

    try:
        controls = _inspect_controls(template_bytes, filename=filename)
    except Exception as exc:
        normalized = normalize_template_extraction_error(exc)
        if normalized is exc:
            raise
        raise normalized from exc
    return tuple(
        TemplatePlaceholderSpec(
            name=control.name,
            label=control.label,
            kind=control.kind,
            hint=control.hint or None,
            location=control.location,
        )
        for control in controls
    )


def inspect_docx_template_bytes(
    template_bytes: bytes,
    *,
    filename: str,
) -> list[dict[str, str | None]]:
    """List the fill targets as plain records: name, label, kind, hint, location."""

    return [
        asdict(spec)
        for spec in inspect_docx_template_placeholders(
            template_bytes, filename=filename
        )
    ]


def docx_template_placeholder_names(
    template_bytes: bytes,
    *,
    filename: str,
) -> tuple[str, ...]:
    """Return each target name once, in document order."""

    return tuple(
        str(item["name"])
        for item in inspect_docx_template_bytes(template_bytes, filename=filename)
    )


def render_docx_template(
    *,
    template_bytes: bytes,
    context: Mapping[str, str | None],
    step_order: int,
    limits: DocumentRenderLimits = DEFAULT_DOCUMENT_RENDER_LIMITS,
) -> tuple[bytes, str, str]:
    """Fill every control from ``context`` and return the finished document.

    Value semantics per target: a missing key or a ``None`` value is an error
    (nothing was produced for a target the template requires); an empty
    string is a deliberate omission and removes the control while the static
    content around it stays; rich targets parse their text as markdown and
    text targets take the text as is. The whole document is held to the
    render limits before anything is written.
    """

    filename = f"step_{step_order}_output.docx"
    try:
        validate_docx_template_archive(template_bytes, filename=filename)
        document = Document(io.BytesIO(template_bytes))
        controls = inspect_content_controls(document)
    except DocxTemplateContractError as exc:
        raise TypedIOValidationException(
            f"The published DOCX template is no longer fillable: {exc}",
            code=FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED.value,
        ) from exc

    _require_values(controls, context)
    sections = _parse_rich_sections(controls, context, limits=limits)

    writer = DocxBlockWriter(document)
    for control in controls:
        value = context[control.name]
        assert value is not None  # _require_values
        if not value.strip():
            remove_control(control)
            continue
        if control.kind == "rich":
            fill_rich_control(
                control,
                writer.elements(
                    sections[control.name],
                    heading_base=control.heading_level,
                    section_label=f"the section '{control.label}'",
                ),
            )
        else:
            fill_text_control(control, value)

    output = io.BytesIO()
    document.save(output)
    return output.getvalue(), _DOCX_MIMETYPE, filename


def extract_docx_text(document_bytes: bytes) -> str:
    """Read the body text, including content inside controls and tables.

    Uses the same reader as uploaded DOCX files (``docx2python``), which walks
    structured document tags; python-docx's paragraph API does not. Headers
    and footers are left out: they hold page furniture (logo, page numbers),
    never step content.
    """

    with tempfile.TemporaryDirectory(prefix="flow-docx-text-") as temp_dir:
        path = Path(temp_dir) / "document.docx"
        path.write_bytes(document_bytes)
        try:
            with docx2python(path) as content:
                paragraphs = [
                    paragraph.strip()
                    for table in content.body
                    for row in table
                    for cell in row
                    for paragraph in cell
                    if paragraph.strip()
                ]
        except Exception as exc:
            raise CorruptFileError("document.docx", str(exc)) from exc
    return "\n\n".join(paragraphs)


def extract_docx_template_text_preview(template_bytes: bytes) -> str:
    return extract_docx_text(template_bytes)[:_PREVIEW_CHARS]


def _inspect_controls(
    template_bytes: bytes, *, filename: str
) -> tuple[ContentControl, ...]:
    validate_docx_template_archive(template_bytes, filename=filename)
    document = Document(io.BytesIO(template_bytes))
    return inspect_content_controls(document)


def _require_values(
    controls: tuple[ContentControl, ...],
    context: Mapping[str, str | None],
) -> None:
    missing = sorted(
        control.name for control in controls if control.name not in context
    )
    if missing:
        raise TypedIOValidationException(
            f"Unresolved template placeholders: {', '.join(missing)}",
            code=FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED.value,
        )
    absent = sorted(
        control.name for control in controls if context[control.name] is None
    )
    if absent:
        raise TypedIOValidationException(
            "Template placeholders without a value: "
            f"{', '.join(absent)}. The bound step or field produced nothing; bind "
            "another source or leave the placeholder empty on purpose.",
            code=FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED.value,
        )
    non_text = sorted(
        control.name
        for control in controls
        if not isinstance(context[control.name], str)
    )
    if non_text:
        raise TypedIOValidationException(
            f"Template placeholders must be bound to text: {', '.join(non_text)}",
            code=FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED.value,
        )


def _parse_rich_sections(
    controls: tuple[ContentControl, ...],
    context: Mapping[str, str | None],
    *,
    limits: DocumentRenderLimits,
) -> dict[str, list[DocumentBlock]]:
    rich_values = {
        control.name: str(context[control.name])
        for control in controls
        if control.kind == "rich" and str(context[control.name]).strip()
    }
    ensure_source_within_limits("\n".join(rich_values.values()), limits=limits)
    sections = {
        name: parse_markdown_blocks(value.splitlines())
        for name, value in rich_values.items()
    }
    ensure_blocks_within_limits(
        [block for blocks in sections.values() for block in blocks],
        limits=limits,
    )
    return sections
