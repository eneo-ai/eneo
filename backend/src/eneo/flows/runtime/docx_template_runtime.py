"""DOCX template inspection, fill and text extraction for flows.

Templates carry their fill targets as Word content controls: the tag is the
target's identity, the alias its label and the placeholder text its authoring
hint. The shared tool runtime reads and fills them; this module holds a
template to the flow profile below, checks the values a fill gets, and reads
the finished document through the same reader every uploaded DOCX goes
through, so control content is never invisible to the run's text output.

Flow profile:
- rich text controls directly in the document body take Markdown sections,
  written with the template's own styles;
- inline text controls directly inside a paragraph take one line of text, or
  several when the plain text control is marked multi-line.

Refused at inspection, before a template can be selected: controls without a
tag, duplicate tags, nested controls, controls mapped to custom XML, other
control kinds (date, picture, drop-down and the like) and controls in a header,
footer or table cell. ``{{name}}`` placeholders are not fill targets.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal

from eneo.document_templates import runtime_client
from eneo.files.docx_template_validation import (
    normalize_template_extraction_error,
    validate_docx_template_archive,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.runtime.document_rendering.blocks import (
    DocumentBlock,
    normalize_document_headings,
)
from eneo.flows.runtime.document_rendering.limits import (
    DEFAULT_DOCUMENT_RENDER_LIMITS,
    DocumentRenderLimits,
    ensure_blocks_within_limits,
    ensure_source_within_limits,
)
from eneo.flows.runtime.document_rendering.markdown_blocks import (
    parse_markdown_blocks,
)
from eneo.flows.runtime.document_rendering.markdown_projection import (
    blocks_to_markdown,
)
from eneo.main.exceptions import (
    BadRequestException,
    FileNotSupportedException,
    TypedIOValidationException,
)
from eneo.main.logging import get_logger

logger = get_logger(__name__)

ContentControlKind = Literal["rich", "text"]

_PREVIEW_CHARS = 2000


class DocxTemplateContractError(BadRequestException):
    """The template's controls fall outside the flow profile."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message, code=code)


@dataclass(frozen=True, slots=True)
class TemplatePlaceholderSpec:
    """One fill target as callers outside the runtime see it."""

    name: str
    label: str
    kind: ContentControlKind
    hint: str | None
    location: str
    section_heading: str | None = None


@dataclass(frozen=True, slots=True)
class _Target:
    spec: TemplatePlaceholderSpec
    # The level of the heading the control sits under; a rich section's
    # headings are written below it.
    heading_level: int


async def inspect_docx_template_placeholders(
    template_bytes: bytes,
    *,
    filename: str,
) -> tuple[TemplatePlaceholderSpec, ...]:
    """List the template's fill targets in document order; none for a
    document without controls."""

    targets = await _inspect(template_bytes, filename=filename)
    return tuple(target.spec for target in targets)


async def inspect_docx_template_bytes(
    template_bytes: bytes,
    *,
    filename: str,
) -> list[dict[str, str | None]]:
    """List the fill targets and their section context as plain records."""

    placeholders = await inspect_docx_template_placeholders(
        template_bytes, filename=filename
    )
    _require_fill_targets(placeholders)
    return [asdict(spec) for spec in placeholders]


async def docx_template_placeholder_names(
    template_bytes: bytes,
    *,
    filename: str,
) -> tuple[str, ...]:
    """Return each target name once, in document order."""

    return tuple(
        str(item["name"])
        for item in await inspect_docx_template_bytes(template_bytes, filename=filename)
    )


async def render_docx_template(
    *,
    template_bytes: bytes,
    template_name: str,
    context: Mapping[str, str | None],
    step_order: int,
    limits: DocumentRenderLimits = DEFAULT_DOCUMENT_RENDER_LIMITS,
) -> tuple[bytes, str, str]:
    """Fill every control and return the document, its mimetype and its text.

    The text is the body as ``extract_docx_text`` reads it, the same value the
    render limits were checked against.

    Value semantics per target: a missing key or a ``None`` value is an error
    (nothing was produced for a target the template requires); an empty
    string is a deliberate omission and removes the control while the static
    content around it stays; rich targets parse their text as Markdown and
    text targets take the text as is. The whole document is held to the
    render limits before the runtime writes anything.
    """

    try:
        targets = await _inspect(template_bytes, filename=template_name)
        _require_fill_targets(targets)
    except (BadRequestException, FileNotSupportedException) as exc:
        if exc.code == FlowApiErrorCode.DOCUMENT_RUNTIME_REQUIRED.value:
            raise _runtime_unavailable_during_render() from exc
        logger.warning(
            "Published DOCX template could not be parsed",
            extra={"step_order": step_order, "code": exc.code},
        )
        raise TypedIOValidationException(
            f"The published DOCX template is no longer fillable: {exc}",
            code=FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED.value,
        ) from exc

    specs = [target.spec for target in targets]
    values = _require_values(specs, context)
    ensure_source_within_limits("\n".join(values.values()), limits=limits)
    sections = {
        spec.name: parse_markdown_blocks(values[spec.name].splitlines())
        for spec in specs
        if spec.kind == "rich" and values[spec.name].strip()
    }
    ensure_blocks_within_limits(
        [block for blocks in sections.values() for block in blocks],
        limits=limits,
        additional_text_chars=sum(
            len(values[spec.name]) for spec in specs if spec.kind == "text"
        ),
    )
    fill: dict[str, str] = {}
    for target in targets:
        name = target.spec.name
        if not values[name].strip():
            # The runtime removes a control bound to the empty string.
            fill[name] = ""
        elif target.spec.kind == "rich":
            fill[name] = _rich_markdown(sections[name], target)
        else:
            fill[name] = values[name]
    try:
        document, mimetype = await runtime_client.render_document(
            output_type="docx", template=template_bytes, values=fill
        )
    except runtime_client.RuntimeUnavailable as exc:
        raise _runtime_unavailable_during_render() from exc
    except BadRequestException as exc:
        raise TypedIOValidationException(
            "The template could not be filled within its limits.",
            code=FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED.value,
        ) from exc
    text = extract_docx_text(document)
    ensure_source_within_limits(text, limits=limits)
    return document, mimetype, text


def extract_docx_text(document_bytes: bytes) -> str:
    """Read the body text, including content inside controls and tables.

    Headers and footers are left out: they hold page furniture (logo, page
    numbers), never step content.
    """

    from eneo.files.text import extract_docx_body_text

    validate_docx_template_archive(document_bytes, filename="document.docx")
    return extract_docx_body_text(document_bytes)


def extract_docx_template_text_preview(template_bytes: bytes) -> str:
    return extract_docx_text(template_bytes)[:_PREVIEW_CHARS]


async def _inspect(template_bytes: bytes, *, filename: str) -> tuple[_Target, ...]:
    try:
        validate_docx_template_archive(template_bytes, filename=filename)
        report = await runtime_client.inspect_template(template_bytes)
    except runtime_client.RuntimeUnavailable as exc:
        raise _runtime_required() from exc
    except Exception as exc:
        normalized = normalize_template_extraction_error(exc)
        if normalized is exc:
            raise
        raise normalized from exc
    if report is None:
        raise _runtime_required()
    return _flow_targets(report.placeholders)


def _flow_targets(placeholders: Sequence[Mapping[str, Any]]) -> tuple[_Target, ...]:
    seen: set[str] = set()
    targets: list[_Target] = []
    for placeholder in placeholders:
        if placeholder.get("syntax") != "control":
            continue
        name = str(placeholder.get("name") or "")
        label = str(placeholder.get("label") or name)
        _refuse_outside_profile(placeholder, name=name, label=label)
        if name in seen:
            raise DocxTemplateContractError(
                f"Two content controls share the tag '{name}'. Tags must be "
                "unique so the flow knows where each value belongs.",
                code=FlowApiErrorCode.TEMPLATE_CONTROL_DUPLICATE.value,
            )
        seen.add(name)
        kind: ContentControlKind = (
            "rich" if placeholder.get("kind") == "rich" else "text"
        )
        hint = placeholder.get("hint")
        section_heading = placeholder.get("section_heading")
        targets.append(
            _Target(
                spec=TemplatePlaceholderSpec(
                    name=name,
                    label=label,
                    kind=kind,
                    hint=str(hint) if hint else None,
                    location=str(placeholder.get("location") or "body"),
                    section_heading=str(section_heading) if section_heading else None,
                ),
                heading_level=int(placeholder.get("heading_level") or 0),
            )
        )
    return tuple(targets)


def _refuse_outside_profile(
    placeholder: Mapping[str, Any], *, name: str, label: str
) -> None:
    reason_code = placeholder.get("reason_code")
    location = placeholder.get("location") or "body"
    if reason_code == "untagged" or not name:
        raise DocxTemplateContractError(
            f"A content control ('{label or 'untitled'}') has no tag. Give every "
            "control a tag in Word (Developer > Properties) so the flow can "
            "address it.",
            code=FlowApiErrorCode.TEMPLATE_CONTROL_UNTAGGED.value,
        )
    if location != "body":
        raise DocxTemplateContractError(
            f"The content control '{name}' is placed in the document {location}. "
            "Controls are supported in the document body only.",
            code=FlowApiErrorCode.TEMPLATE_CONTROL_PLACEMENT.value,
        )
    if reason_code == "nested":
        raise DocxTemplateContractError(
            f"The content control '{name}' is nested inside another control. "
            "Nested controls are not supported.",
            code=FlowApiErrorCode.TEMPLATE_CONTROL_NESTED.value,
        )
    if placeholder.get("in_table"):
        raise DocxTemplateContractError(
            f"The content control '{name}' is placed in a table cell. Controls "
            "are supported between paragraphs and inside paragraphs only.",
            code=FlowApiErrorCode.TEMPLATE_CONTROL_PLACEMENT.value,
        )
    if reason_code == "data_bound":
        raise DocxTemplateContractError(
            f"The content control '{name}' is mapped to custom XML data. Remove "
            "the XML mapping; the flow writes the control's content directly.",
            code=FlowApiErrorCode.TEMPLATE_CONTROL_MAPPED.value,
        )
    if reason_code == "unsupported_kind" or not placeholder.get("supported"):
        reason = placeholder.get("reason") or "an unsupported kind of"
        raise DocxTemplateContractError(
            f"The content control '{name}' cannot be filled ({reason}). Use a "
            "rich text control for sections and a plain text control for single "
            "values.",
            code=FlowApiErrorCode.TEMPLATE_CONTROL_UNSUPPORTED.value,
        )
    container = placeholder.get("container")
    rich = placeholder.get("kind") == "rich"
    if (rich and container != "part") or (not rich and container != "paragraph"):
        raise DocxTemplateContractError(
            f"The content control '{name}' has an unsupported placement. Place "
            "rich text controls directly in the document body and inline text "
            "controls directly inside a paragraph.",
            code=FlowApiErrorCode.TEMPLATE_CONTROL_PLACEMENT.value,
        )


def _require_fill_targets(targets: Sequence[object]) -> None:
    if not targets:
        raise DocxTemplateContractError(
            "A DOCX template must contain at least one supported Word content control. "
            "Replace any {{...}} placeholders with tagged content controls in Word.",
            code=FlowApiErrorCode.TEMPLATE_NO_CONTROLS.value,
        )


def _require_values(
    targets: Sequence[TemplatePlaceholderSpec],
    context: Mapping[str, str | None],
) -> dict[str, str]:
    missing = sorted(target.name for target in targets if target.name not in context)
    if missing:
        raise TypedIOValidationException(
            f"Unresolved template placeholders: {', '.join(missing)}",
            code=FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED.value,
        )
    absent = sorted(target.name for target in targets if context[target.name] is None)
    if absent:
        raise TypedIOValidationException(
            "Template placeholders without a value: "
            f"{', '.join(absent)}. The bound step or field produced nothing; bind "
            "another source or leave the placeholder empty on purpose.",
            code=FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED.value,
        )
    values: dict[str, str] = {}
    non_text: list[str] = []
    for target in targets:
        value = context[target.name]
        if isinstance(value, str):
            values[target.name] = value
        else:
            non_text.append(target.name)
    if non_text:
        raise TypedIOValidationException(
            f"Template placeholders must be bound to text: {', '.join(sorted(non_text))}",
            code=FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED.value,
        )
    return values


def _rich_markdown(blocks: list[DocumentBlock], target: _Target) -> str:
    """The section as Markdown with its headings numbered from 1; the runtime
    writes them below the heading the control sits under."""

    return blocks_to_markdown(
        normalize_document_headings(
            blocks,
            heading_base=target.heading_level,
            section_label=f"the section '{target.spec.label}'",
        )
    )


def _runtime_required() -> BadRequestException:
    return BadRequestException(
        "Configure an available shared document runtime before using Word templates.",
        code=FlowApiErrorCode.DOCUMENT_RUNTIME_REQUIRED.value,
    )


def _runtime_unavailable_during_render() -> TypedIOValidationException:
    return TypedIOValidationException(
        "The shared document runtime is unavailable.",
        code=FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED.value,
    )
