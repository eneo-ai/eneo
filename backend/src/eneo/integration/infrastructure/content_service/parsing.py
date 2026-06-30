"""Pure parsing / content helpers for the SharePoint content service.

These are stateless functions extracted from sharepoint_content_service.py so the
content-handling logic can be read and tested in isolation. No service, token, or
I/O dependencies.
"""

from typing import Any, Optional, cast

from html2text import html2text

from eneo.integration.infrastructure.content_service.types import SharePointItem


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


# File extensions that cannot produce useful text content.
# These are skipped before download to save bandwidth and avoid database pollution.
_UNSUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Images
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".svg",
        ".ico",
        ".webp",
        ".tiff",
        ".tif",
        ".heic",
        ".heif",
        ".raw",
        ".cr2",
        ".nef",
        ".arw",
        ".psd",
        # Video
        ".mp4",
        ".avi",
        ".mov",
        ".wmv",
        ".mkv",
        ".webm",
        ".flv",
        ".m4v",
        # Audio
        ".mp3",
        ".wav",
        ".ogg",
        ".flac",
        ".aac",
        ".wma",
        ".m4a",
        # Archives
        ".zip",
        ".rar",
        ".7z",
        ".tar",
        ".gz",
        ".bz2",
        # Executables / binaries
        ".exe",
        ".dll",
        ".msi",
        ".bin",
        ".iso",
        # Other non-text
        ".ttf",
        ".otf",
        ".woff",
        ".woff2",
    }
)


def unsupported_file_reason(filename: str) -> Optional[str]:
    """Return a skip reason if the file type is unsupported, or None if OK."""
    name = filename.lower()
    for ext in _UNSUPPORTED_EXTENSIONS:
        if name.endswith(ext):
            # Determine a human-readable category
            if ext in {
                ".jpg",
                ".jpeg",
                ".png",
                ".gif",
                ".bmp",
                ".svg",
                ".ico",
                ".webp",
                ".tiff",
                ".tif",
                ".heic",
                ".heif",
                ".raw",
                ".cr2",
                ".nef",
                ".arw",
                ".psd",
            }:
                return "Unsupported file type (image)"
            if ext in {".mp4", ".avi", ".mov", ".wmv", ".mkv", ".webm", ".flv", ".m4v"}:
                return "Unsupported file type (video)"
            if ext in {".mp3", ".wav", ".ogg", ".flac", ".aac", ".wma", ".m4a"}:
                return "Unsupported file type (audio)"
            return f"Unsupported file type ({ext})"
    return None
