"""Writer guidance derived from what the document renderers actually support.

One owner for the sentences every document-producing prompt carries, so the
model is told exactly the markdown subset the block model renders and the
structure rules the writers enforce (see ``blocks.py`` and ``docx_writer``).
"""

from __future__ import annotations

from eneo.flows.runtime.document_rendering.blocks import (
    MAX_HEADING_LEVEL,
    MAX_LIST_LEVEL,
)

_SUPPORTED_MARKDOWN = (
    "Supported Markdown: headings, paragraphs separated by blank lines, "
    f"'-' bullet lists and '1.' numbered lists nested at most {MAX_LIST_LEVEL + 1} "
    "levels, pipe tables with a header row, **bold**, *italic*, `code` and "
    "[text](https://…) links. HTML, images and other syntax are not rendered."
)
_NO_PLACEHOLDERS = (
    "Never write bracketed placeholders such as [Infoga datum] or [Namn]; omit "
    "what you do not know. The template controls fonts, sizes, spacing and page "
    "layout, so do not add blank lines or formatting for spacing."
)


def document_markdown_guidance(*, artifact_name: str) -> tuple[str, ...]:
    """Guidance for a step whose whole answer becomes one document."""

    return (
        f"The system will render your answer into a {artifact_name} file after "
        "you respond.",
        "Return only the document body as Markdown: begin with the document "
        "title as a level-1 heading and write nothing before it and nothing "
        "after the body (no introduction, greeting, commentary or closing remark).",
        "Use heading levels in order without skipping ('##' under '#', '###' "
        f"under '##'), at most {MAX_HEADING_LEVEL} levels.",
        _SUPPORTED_MARKDOWN,
        _NO_PLACEHOLDERS,
        "Do not output binary file contents, base64, XML/ZIP internals, or PDF "
        "object syntax.",
    )


def section_markdown_guidance() -> str:
    """Guidance for a field whose text fills one section of a Word template."""

    return (
        "Write the section body as Markdown without a title for the section "
        "itself: paragraphs, lists and pipe tables as needed, and sub-headings "
        "that start at '##' and follow in order; they are placed under the "
        "section's own heading automatically. Write no introduction or closing "
        "remark and no bracketed placeholders; leave the field empty when there "
        "is nothing to say. " + _SUPPORTED_MARKDOWN
    )


def text_field_guidance() -> str:
    """Guidance for a field that fills one single-line value."""

    return "One line of plain text without Markdown; leave it empty when unknown."
