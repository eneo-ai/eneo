"""Manufacture Word content-control fixtures without any production renderer."""

from typing import Any

from docx.oxml import OxmlElement as word_element
from docx.oxml.ns import qn

_PLACEHOLDER_STYLE_ID = "PlaceholderText"
_control_ids = iter(range(100_000, 10_000_000))


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
