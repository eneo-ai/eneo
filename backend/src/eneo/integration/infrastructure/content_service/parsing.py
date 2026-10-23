"""Pure parsing / content helpers for the SharePoint content service.

These are stateless functions extracted from sharepoint_content_service.py so the
content-handling logic can be read and tested in isolation. No service, token, or
I/O dependencies.
"""

from typing import Any, Optional, cast

from html2text import html2text

from eneo.integration.infrastructure.content_service.types import SharePointItem
from eneo.integration.infrastructure.content_service.utils import (
    unsupported_file_reason,
)

__all__ = [
    "extract_text_from_canvas_layout",
    "has_graph_facet",
    "require_text",
    "safe_int",
    "sanitize_text_for_db",
    "unsupported_file_reason",
]


def extract_text_from_canvas_layout(content: dict[str, Any]) -> str:
    """Extract plain text from a SharePoint page's canvasLayout structure.

    Parses horizontalSections and verticalSection to find textWebPart
    elements and converts their innerHtml to plain text.
    """
    texts: list[str] = []
    canvas: dict[str, Any] = content.get("canvasLayout", {})
    if not canvas:
        return ""

    def _extract_from_webparts(webparts: list[dict[str, Any]]) -> None:
        for wp in webparts:
            if wp.get("@odata.type") == "#microsoft.graph.textWebPart":
                inner_html = cast(str, wp.get("innerHtml", ""))
                if inner_html:
                    texts.append(html2text(inner_html).strip())

    for section in canvas.get("horizontalSections", []):
        for column in section.get("columns", []):
            _extract_from_webparts(column.get("webparts", []))

    vertical = canvas.get("verticalSection")
    if vertical:
        _extract_from_webparts(vertical.get("webparts", []))

    return "\n\n".join(texts)


def sanitize_text_for_db(text: str) -> str:
    """Remove null bytes and other invalid characters that PostgreSQL doesn't accept.

    PostgreSQL TEXT columns cannot contain null bytes (0x00) in UTF-8 encoding.
    This commonly happens when PDF extraction fails or returns binary data.
    """
    if not text:
        return text
    # Remove null bytes which cause "invalid byte sequence for encoding UTF8: 0x00"
    return text.replace("\x00", "")


def safe_int(value: Any) -> int:
    """Best-effort int conversion for defensive size accounting."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if not isinstance(value, str):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def has_graph_facet(item: SharePointItem, facet: str) -> bool:
    """Return True for Microsoft Graph facets represented as true or an object."""
    value = cast(dict[str, object], item).get(facet)
    if isinstance(value, bool):
        return value
    return isinstance(value, dict)


def require_text(value: Optional[str], field_name: str) -> str:
    if not value:
        raise ValueError(f"{field_name} is required")
    return value
