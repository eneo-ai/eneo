"""Word content controls (structured document tags) as flow template targets.

A template's fill targets are Word's own content controls (``w:sdt``): the
``w:tag`` is the target's identity, the ``w:alias`` its label and the
placeholder text its authoring hint. This module owns the supported control
profile, discovery, the authoring helpers the standard templates and tests
share, and the fill operations. Everything outside the profile is refused at
inspection, before a template can be selected, so a fill never leaves
placeholder content or breaks a control Word would reload from elsewhere.

Supported profile:
- body-level rich-text controls (``w:sdt`` directly under ``w:body``) take
  paragraphs, lists and tables written with the document's own styles;
- inline text controls (``w:sdt`` inside a paragraph, plain ``w:text`` or
  rich) take one line of text, or several when ``w:text w:multiLine`` is set.

Refused: controls without a tag, duplicate tags, nested controls, controls
mapped to custom XML (``w:dataBinding``), other kinds (date, picture, combo
box, drop-down, checkbox, building block, group, repeating section) and
controls placed in table cells, headers or footers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterator, Literal, Sequence

from docx.oxml.ns import qn

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.runtime.document_rendering.docx_writer import word_element
from eneo.main.exceptions import BadRequestException

ContentControlKind = Literal["rich", "text"]

_HEADING_STYLE_NAME = re.compile(r"^heading (\d)$")
_PLACEHOLDER_STYLE_ID = "PlaceholderText"
_UNSUPPORTED_KIND_TAGS: tuple[tuple[str, str], ...] = (
    ("w:date", "date"),
    ("w:picture", "picture"),
    ("w:comboBox", "combo box"),
    ("w:dropDownList", "drop-down list"),
    ("w14:checkbox", "checkbox"),
    ("w:docPartObj", "building block"),
    ("w:docPartList", "building block"),
    ("w:group", "group"),
    ("w:equation", "equation"),
    ("w:citation", "citation"),
    ("w:bibliography", "bibliography"),
    ("w15:repeatingSection", "repeating section"),
    ("w15:repeatingSectionItem", "repeating section"),
)
_W15_NAMESPACE = "http://schemas.microsoft.com/office/word/2012/wordml"
_W14_NAMESPACE = "http://schemas.microsoft.com/office/word/2010/wordml"


class DocxTemplateContractError(BadRequestException):
    """The template's controls fall outside the supported profile."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message, code=code)


@dataclass(frozen=True, slots=True)
class ContentControl:
    name: str
    label: str
    kind: ContentControlKind
    hint: str
    location: str
    heading_level: int
    multiline: bool
    element: Any


def inspect_content_controls(document: Any) -> tuple[ContentControl, ...]:
    """Return the fill targets of ``document`` in reading order.

    Raises ``DocxTemplateContractError`` for any control outside the profile.
    """

    style_names = _style_names_by_id(document)
    body = document.element.body
    seen: dict[str, str] = {}
    controls: list[ContentControl] = []

    for part_label, root in _story_roots(document):
        for sdt in root.iter(qn("w:sdt")):
            properties = sdt.find(qn("w:sdtPr"))
            tag_value = _property_value(properties, "w:tag")
            label = _property_value(properties, "w:alias") or tag_value or ""
            if not tag_value:
                raise DocxTemplateContractError(
                    f"A content control ('{label or 'untitled'}') has no tag. Give every "
                    "control a tag in Word (Developer > Properties) so the flow can "
                    "address it.",
                    code=FlowApiErrorCode.TEMPLATE_CONTROL_UNTAGGED.value,
                )
            if part_label != "body":
                raise DocxTemplateContractError(
                    f"The content control '{tag_value}' is placed in the document "
                    f"{part_label}. Controls are supported in the document body only.",
                    code=FlowApiErrorCode.TEMPLATE_CONTROL_PLACEMENT.value,
                )
            if any(ancestor.tag == qn("w:sdt") for ancestor in sdt.iterancestors()):
                raise DocxTemplateContractError(
                    f"The content control '{tag_value}' is nested inside another "
                    "control. Nested controls are not supported.",
                    code=FlowApiErrorCode.TEMPLATE_CONTROL_NESTED.value,
                )
            if any(ancestor.tag == qn("w:tc") for ancestor in sdt.iterancestors()):
                raise DocxTemplateContractError(
                    f"The content control '{tag_value}' is placed in a table cell. "
                    "Controls are supported between paragraphs and inside paragraphs "
                    "only.",
                    code=FlowApiErrorCode.TEMPLATE_CONTROL_PLACEMENT.value,
                )
            if (
                properties is not None
                and properties.find(qn("w:dataBinding")) is not None
            ):
                raise DocxTemplateContractError(
                    f"The content control '{tag_value}' is mapped to custom XML data. "
                    "Remove the XML mapping; the flow writes the control's content "
                    "directly.",
                    code=FlowApiErrorCode.TEMPLATE_CONTROL_MAPPED.value,
                )
            unsupported = _unsupported_kind(properties)
            if unsupported is not None:
                raise DocxTemplateContractError(
                    f"The content control '{tag_value}' is a {unsupported} control. "
                    "Use a rich text control for sections and a plain text control "
                    "for single values.",
                    code=FlowApiErrorCode.TEMPLATE_CONTROL_UNSUPPORTED.value,
                )
            if tag_value in seen:
                raise DocxTemplateContractError(
                    f"Two content controls share the tag '{tag_value}'. Tags must be "
                    "unique so the flow knows where each value belongs.",
                    code=FlowApiErrorCode.TEMPLATE_CONTROL_DUPLICATE.value,
                )
            seen[tag_value] = label
            parent = sdt.getparent()
            text_properties = (
                properties.find(qn("w:text")) if properties is not None else None
            )
            if parent is body and text_properties is None:
                kind: ContentControlKind = "rich"
            elif parent is not None and parent.tag == qn("w:p"):
                kind = "text"
            else:
                raise DocxTemplateContractError(
                    f"The content control '{tag_value}' has an unsupported "
                    "placement. Place rich text controls directly in the document "
                    "body and inline text controls directly inside a paragraph.",
                    code=FlowApiErrorCode.TEMPLATE_CONTROL_PLACEMENT.value,
                )
            multiline = text_properties is not None and text_properties.get(
                qn("w:multiLine")
            ) in ("1", "true", "on")
            controls.append(
                ContentControl(
                    name=tag_value,
                    label=label,
                    kind=kind,
                    hint=_control_text(sdt),
                    location="body",
                    heading_level=_preceding_heading_level(
                        sdt if parent is body else parent,
                        style_names=style_names,
                    ),
                    multiline=multiline,
                    element=sdt,
                )
            )
    return tuple(controls)


def fill_rich_control(control: ContentControl, elements: Sequence[Any]) -> None:
    """Replace the control's content with rendered block elements."""

    content = _clear_content(control)
    for element in elements:
        content.append(element)
    if len(content) == 0:
        content.append(word_element("w:p"))


def fill_text_control(control: ContentControl, value: str) -> None:
    """Replace the control's content with one text value.

    Line breaks become ``w:br`` in a multi-line text control and a space
    otherwise; the run inherits the paragraph's formatting.
    """

    content = _clear_content(control)
    run = word_element("w:r")
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not control.multiline:
        lines = [" ".join(lines)]
    for index, line in enumerate(lines):
        if index:
            run.append(word_element("w:br"))
        text = word_element("w:t")
        text.set(qn("xml:space"), "preserve")
        text.text = line
        run.append(text)
    content.append(run)


def remove_control(control: ContentControl) -> None:
    """Drop the control entirely; the surrounding static content stays."""

    parent = control.element.getparent()
    if parent is not None:
        parent.remove(control.element)


# -- authoring helpers (standard templates and tests) --------------------------


def append_rich_control(
    document: Any,
    *,
    tag: str,
    label: str,
    hint: str,
) -> Any:
    """Append a body-level rich text control showing ``hint`` as placeholder text."""

    sdt = _control_element(tag=tag, label=label)
    content = word_element("w:sdtContent")
    paragraph = word_element("w:p")
    paragraph.append(_placeholder_run(hint))
    content.append(paragraph)
    sdt.append(content)
    body = document.element.body
    body.insert(len(body) - 1, sdt)
    _ensure_placeholder_style(document)
    return sdt


def append_text_control(
    paragraph: Any,
    *,
    tag: str,
    label: str,
    hint: str,
    multiline: bool = False,
) -> Any:
    """Append an inline plain text control to ``paragraph``."""

    sdt = _control_element(tag=tag, label=label)
    properties = sdt.find(qn("w:sdtPr"))
    text = word_element("w:text")
    if multiline:
        text.set(qn("w:multiLine"), "1")
    properties.append(text)
    content = word_element("w:sdtContent")
    content.append(_placeholder_run(hint))
    sdt.append(content)
    paragraph._p.append(sdt)
    _ensure_placeholder_style(paragraph.part.package.main_document_part.document)
    return sdt


# -- internals -------------------------------------------------------------------


_control_ids = iter(range(100_000, 10_000_000))


def _control_element(*, tag: str, label: str) -> Any:
    sdt = word_element("w:sdt")
    properties = word_element("w:sdtPr")
    alias = word_element("w:alias")
    alias.set(qn("w:val"), label)
    properties.append(alias)
    tag_element = word_element("w:tag")
    tag_element.set(qn("w:val"), tag)
    properties.append(tag_element)
    identifier = word_element("w:id")
    identifier.set(qn("w:val"), str(next(_control_ids)))
    properties.append(identifier)
    properties.append(word_element("w:showingPlcHdr"))
    sdt.append(properties)
    return sdt


def _placeholder_run(hint: str) -> Any:
    run = word_element("w:r")
    run_properties = word_element("w:rPr")
    run_style = word_element("w:rStyle")
    run_style.set(qn("w:val"), _PLACEHOLDER_STYLE_ID)
    run_properties.append(run_style)
    run.append(run_properties)
    text = word_element("w:t")
    text.set(qn("xml:space"), "preserve")
    text.text = hint
    run.append(text)
    return run


def _ensure_placeholder_style(document: Any) -> None:
    from docx.enum.style import WD_STYLE_TYPE
    from docx.shared import RGBColor

    if any(style.style_id == _PLACEHOLDER_STYLE_ID for style in document.styles):
        return
    style = document.styles.add_style("Placeholder Text", WD_STYLE_TYPE.CHARACTER)
    style.font.color.rgb = RGBColor(0x59, 0x59, 0x59)
    style.font.italic = True


def _clear_content(control: ContentControl) -> Any:
    sdt = control.element
    properties = sdt.find(qn("w:sdtPr"))
    if properties is not None:
        showing = properties.find(qn("w:showingPlcHdr"))
        if showing is not None:
            properties.remove(showing)
    content = sdt.find(qn("w:sdtContent"))
    if content is None:
        content = word_element("w:sdtContent")
        sdt.append(content)
    for child in list(content):
        content.remove(child)
    return content


def _story_roots(document: Any) -> Iterator[tuple[str, Any]]:
    yield "body", document.element.body
    document_part = document.part
    for section in document.sections:
        section_properties = section._sectPr
        for reference in section_properties.findall(qn("w:headerReference")):
            part = _related_part(document_part, reference)
            if part is not None:
                yield "header", part.element
        for reference in section_properties.findall(qn("w:footerReference")):
            part = _related_part(document_part, reference)
            if part is not None:
                yield "footer", part.element


def _related_part(document_part: Any, reference: Any) -> Any | None:
    relationship_id = reference.get(qn("r:id"))
    if relationship_id is None:
        return None
    try:
        return document_part.related_parts[relationship_id]
    except KeyError:
        return None


def _property_value(properties: Any, tag: str) -> str | None:
    if properties is None:
        return None
    element = properties.find(qn(tag))
    if element is None:
        return None
    value = element.get(qn("w:val"))
    return value.strip() if value else None


def _unsupported_kind(properties: Any) -> str | None:
    if properties is None:
        return None
    for tag, label in _UNSUPPORTED_KIND_TAGS:
        prefix, local = tag.split(":")
        namespace = {
            "w": qn("w:x").split("}")[0][1:],
            "w14": _W14_NAMESPACE,
            "w15": _W15_NAMESPACE,
        }[prefix]
        if properties.find(f"{{{namespace}}}{local}") is not None:
            return label
    return None


def _control_text(sdt: Any) -> str:
    content = sdt.find(qn("w:sdtContent"))
    if content is None:
        return ""
    return " ".join(
        "".join(text.text or "" for text in content.iter(qn("w:t"))).split()
    )


def _style_names_by_id(document: Any) -> dict[str, str]:
    return {
        str(style.style_id): str(style.name).casefold() for style in document.styles
    }


def _preceding_heading_level(anchor: Any, *, style_names: dict[str, str]) -> int:
    for sibling in anchor.itersiblings(preceding=True):
        if sibling.tag != qn("w:p"):
            continue
        properties = sibling.find(qn("w:pPr"))
        style = properties.find(qn("w:pStyle")) if properties is not None else None
        if style is None:
            continue
        match = _HEADING_STYLE_NAME.match(
            style_names.get(style.get(qn("w:val"), ""), "")
        )
        if match:
            return int(match.group(1))
    return 0
