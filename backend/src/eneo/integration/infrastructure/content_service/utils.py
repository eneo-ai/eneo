"""Text extraction for files downloaded from SharePoint.

Office and PDF bytes go through the same sandboxed extractor as uploads and
crawls: a disposable child process with memory, CPU, archive, output and
deadline limits (``eneo.files.bounded_extraction``). Skip reasons and their
codes are owned by ``eneo.integration.domain.skip_reasons``.
"""

import tempfile
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path
from typing import Any, Optional

from eneo.files.bounded_extraction import extract_in_process
from eneo.files.extraction_limits import (
    FileExtractionLimits,
    get_file_extraction_limits,
)
from eneo.files.text import (
    CorruptFileError,
    EncryptedFileError,
    ExtractionError,
    ExtractionLimitError,
    PdfPageLimitError,
    TextSanitizer,
    UnsupportedFormatError,
)
from eneo.integration.domain.skip_reasons import (
    CORRUPT_FILE_REASON,
    EMPTY_CONTENT_REASON,
    NO_TEXT_LAYER_REASON,
    NO_TEXT_REASONS,
    PASSWORD_PROTECTED_REASON,
    error_reason,
    extraction_limit_reason,
    file_too_large_reason,
    unsupported_type_reason,
)
from eneo.integration.infrastructure.content_service.types import SharePointItem

logger = getLogger(__name__)

# The skip reasons (user-facing, matched in tests) are defined with their
# codes in eneo.integration.domain.skip_reasons and re-exported here.
__all__ = [
    "CORRUPT_FILE_REASON",
    "EMPTY_CONTENT_REASON",
    "NO_TEXT_LAYER_REASON",
    "NO_TEXT_REASONS",
    "PASSWORD_PROTECTED_REASON",
    "ExtractionResult",
    "error_reason",
    "extraction_limit_reason",
    "file_too_large_reason",
    "unsupported_file_reason",
    "unsupported_package_reason",
    "unsupported_type_reason",
]


@dataclass(frozen=True)
class ExtractionResult:
    """Outcome of turning downloaded bytes into text.

    Exactly one of ``text`` (non-empty) and ``skip_reason`` is set. ``failed``
    marks parser failures, corrupt or encrypted files and truncated downloads:
    nothing may be concluded about the file, so callers must not delete.
    """

    text: Optional[str] = None
    skip_reason: Optional[str] = None
    failed: bool = False
    content_type: str = ""

    def __post_init__(self) -> None:
        if (self.text is None) == (self.skip_reason is None):
            raise ValueError("ExtractionResult needs exactly one of text/skip_reason")
        if self.text is not None and not self.text.strip():
            raise ValueError("ExtractionResult.text must not be empty")
        if self.failed and self.text is not None:
            raise ValueError("A failed ExtractionResult cannot carry text")

    @property
    def is_no_text(self) -> bool:
        return self.skip_reason in NO_TEXT_REASONS

    @classmethod
    def ok(cls, text: str, content_type: str = "") -> "ExtractionResult":
        return cls(text=text, content_type=content_type)

    @classmethod
    def no_text(cls, reason: str, content_type: str = "") -> "ExtractionResult":
        if reason not in NO_TEXT_REASONS:
            raise ValueError(f"Not a no-text reason: {reason}")
        return cls(skip_reason=reason, content_type=content_type)

    @classmethod
    def skipped(cls, reason: str, content_type: str = "") -> "ExtractionResult":
        return cls(skip_reason=reason, content_type=content_type)

    @classmethod
    def error(cls, detail: str, content_type: str = "") -> "ExtractionResult":
        return cls(
            skip_reason=error_reason(detail), failed=True, content_type=content_type
        )


def is_unextractable_content(text: Optional[str]) -> bool:
    """True when extraction produced no usable text."""
    return not text or not text.strip()


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

PDF_KIND = "pdf"
DOCX_KIND = "docx"
XLSX_KIND = "xlsx"
PPTX_KIND = "pptx"
TEXT_KIND = "text"
UNSUPPORTED_KIND = "unsupported"
UNKNOWN_KIND = "unknown"

_KIND_BY_EXTENSION: dict[str, str] = {
    ".pdf": PDF_KIND,
    ".docx": DOCX_KIND,
    ".docm": DOCX_KIND,
    ".xlsx": XLSX_KIND,
    ".xlsm": XLSX_KIND,
    # Legacy BIFF workbooks are read by calamine, the same engine uploads use.
    ".xls": XLSX_KIND,
    ".pptx": PPTX_KIND,
    ".pptm": PPTX_KIND,
    ".txt": TEXT_KIND,
    ".md": TEXT_KIND,
    ".markdown": TEXT_KIND,
    ".csv": TEXT_KIND,
    ".tsv": TEXT_KIND,
    ".json": TEXT_KIND,
    ".xml": TEXT_KIND,
    ".html": TEXT_KIND,
    ".htm": TEXT_KIND,
    ".log": TEXT_KIND,
    ".rst": TEXT_KIND,
    ".yaml": TEXT_KIND,
    ".yml": TEXT_KIND,
}

_KIND_BY_CONTENT_TYPE: dict[str, str] = {
    "application/pdf": PDF_KIND,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DOCX_KIND,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": XLSX_KIND,
    "application/vnd.ms-excel": XLSX_KIND,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": PPTX_KIND,
    "application/json": TEXT_KIND,
    "application/xml": TEXT_KIND,
    "application/csv": TEXT_KIND,
    "application/x-yaml": TEXT_KIND,
}

_IMAGE_LABEL = "image"
_VIDEO_LABEL = "video"
_AUDIO_LABEL = "audio"
_LEGACY_WORD_LABEL = "legacy Word .doc, save as .docx"
_LEGACY_POWERPOINT_LABEL = "legacy PowerPoint .ppt, save as .pptx"
_ONENOTE_LABEL = "OneNote"
_OUTLOOK_LABEL = "Outlook .msg"
_RTF_LABEL = "rich text .rtf"
_OPENDOCUMENT_LABEL = "OpenDocument"

# Extensions that never produce usable text. Checked before download so the
# bytes are not fetched, and again after download for content-type matches.
_UNSUPPORTED_EXTENSIONS: dict[str, str] = {
    **{
        ext: _IMAGE_LABEL
        for ext in (
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
        )
    },
    **{
        ext: _VIDEO_LABEL
        for ext in (".mp4", ".avi", ".mov", ".wmv", ".mkv", ".webm", ".flv", ".m4v")
    },
    **{
        ext: _AUDIO_LABEL
        for ext in (".mp3", ".wav", ".ogg", ".flac", ".aac", ".wma", ".m4a")
    },
    **{
        ext: ext
        for ext in (
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
            # Fonts
            ".ttf",
            ".otf",
            ".woff",
            ".woff2",
            # Other Office family formats without a parser in the platform
            ".xlsb",
            ".vsd",
            ".vsdx",
            ".pub",
            ".mpp",
            ".pages",
            ".numbers",
            ".key",
        )
    },
    ".doc": _LEGACY_WORD_LABEL,
    ".dot": _LEGACY_WORD_LABEL,
    ".ppt": _LEGACY_POWERPOINT_LABEL,
    ".pps": _LEGACY_POWERPOINT_LABEL,
    ".pot": _LEGACY_POWERPOINT_LABEL,
    ".one": _ONENOTE_LABEL,
    ".onetoc2": _ONENOTE_LABEL,
    ".onepkg": _ONENOTE_LABEL,
    ".msg": _OUTLOOK_LABEL,
    ".rtf": _RTF_LABEL,
    ".odt": f"{_OPENDOCUMENT_LABEL} .odt",
    ".ods": f"{_OPENDOCUMENT_LABEL} .ods",
    ".odp": f"{_OPENDOCUMENT_LABEL} .odp",
}

_UNSUPPORTED_CONTENT_TYPES: dict[str, str] = {
    "application/msword": _LEGACY_WORD_LABEL,
    "application/vnd.ms-powerpoint": _LEGACY_POWERPOINT_LABEL,
    "application/onenote": _ONENOTE_LABEL,
    "application/msonenote": _ONENOTE_LABEL,
    "application/vnd.ms-outlook": _OUTLOOK_LABEL,
    "application/rtf": _RTF_LABEL,
    "text/rtf": _RTF_LABEL,
    "application/vnd.oasis.opendocument.text": f"{_OPENDOCUMENT_LABEL} .odt",
    "application/vnd.oasis.opendocument.spreadsheet": f"{_OPENDOCUMENT_LABEL} .ods",
    "application/vnd.oasis.opendocument.presentation": f"{_OPENDOCUMENT_LABEL} .odp",
}

_UNSUPPORTED_CONTENT_TYPE_PREFIXES: dict[str, str] = {
    "image/": _IMAGE_LABEL,
    "video/": _VIDEO_LABEL,
    "audio/": _AUDIO_LABEL,
}


def _extension(filename: str) -> str:
    return Path(filename.lower()).suffix


def _base_mime(content_type: str) -> str:
    return content_type.split(";")[0].strip().lower()


def unsupported_file_reason(filename: str) -> Optional[str]:
    """Skip reason for a file type that can never yield text, else None."""
    label = _UNSUPPORTED_EXTENSIONS.get(_extension(filename))
    return unsupported_type_reason(label) if label else None


def unsupported_package_reason(item: SharePointItem) -> Optional[str]:
    """Skip reason for a package (a OneNote notebook): a folder Graph serves
    without a folder facet and without a download."""
    package = item.get("package")
    if not isinstance(package, dict):
        return None
    label = _ONENOTE_LABEL if package.get("type") == "oneNote" else "package"
    return unsupported_type_reason(label)


def _unsupported_content_type_label(mime: str) -> Optional[str]:
    label = _UNSUPPORTED_CONTENT_TYPES.get(mime)
    if label:
        return label
    for prefix, prefix_label in _UNSUPPORTED_CONTENT_TYPE_PREFIXES.items():
        if mime.startswith(prefix):
            return prefix_label
    return None


def detect_content_type(content_type: str, filename: str) -> str:
    """Pick the parser for a download.

    A known extension wins over the Content-Type header: SharePoint derives
    the header from the name anyway, and an HTML error page served for a .pdf
    must fail in the PDF parser rather than be indexed as text. The header
    decides only for unknown or missing extensions, and generic types such as
    application/octet-stream never decide.
    """
    ext = _extension(filename)
    mime = _base_mime(content_type)

    if ext in _UNSUPPORTED_EXTENSIONS:
        return UNSUPPORTED_KIND
    if ext in _KIND_BY_EXTENSION:
        return _KIND_BY_EXTENSION[ext]
    if _unsupported_content_type_label(mime):
        return UNSUPPORTED_KIND
    if mime in _KIND_BY_CONTENT_TYPE:
        return _KIND_BY_CONTENT_TYPE[mime]
    if mime.startswith("text/") or mime.endswith("+xml") or mime.endswith("+json"):
        return TEXT_KIND
    return UNKNOWN_KIND


def file_extension_to_type(filename: str) -> str:
    """Coarse item category used for SharePoint item metadata."""
    name = filename.lower()
    if name.endswith((".docx", ".doc")):
        return "document"
    elif name.endswith((".xlsx", ".xls")):
        return "spreadsheet"
    elif name.endswith((".pptx", ".ppt")):
        return "presentation"
    elif name.endswith((".pdf")):
        return "pdf"
    elif name.endswith((".txt", ".md", ".html", ".htm")):
        return "text"
    elif name.endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp")):
        return "image"
    else:
        return "file"


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")


def _looks_binary(payload: bytes) -> bool:
    # A NUL byte in the leading chunk marks binary content; UTF-8/cp1252 text
    # never contains one. UTF-16 is the exception and is decoded by its BOM.
    return b"\x00" in payload[:8192] and not payload.startswith(_UTF16_BOMS)


def _decode_text(payload: bytes, charset: Optional[str]) -> str:
    if payload.startswith(_UTF16_BOMS):
        return payload.decode("utf-16", errors="replace")
    candidates = [charset] if charset else []
    candidates += ["utf-8", "cp1252"]
    for encoding in candidates:
        try:
            return payload.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return payload.decode("utf-8", errors="replace")


# The sandboxed worker picks its parser by mimetype. The kind decided here
# (extension first) wins over the Content-Type header, so the worker is given
# the canonical type for the kind rather than what SharePoint announced.
_MIME_BY_KIND: dict[str, str] = {
    PDF_KIND: "application/pdf",
    DOCX_KIND: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    XLSX_KIND: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    PPTX_KIND: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


async def _parse_in_sandbox(
    kind: str, payload: bytes, filename: str, limits: FileExtractionLimits
) -> str:
    with tempfile.TemporaryDirectory(prefix="sharepoint-extract-") as tmp:
        # Keep the extension so parsers see the same name shape as uploads.
        path = Path(tmp) / f"download{_extension(filename)}"
        path.write_bytes(payload)
        text = await extract_in_process(
            path, _MIME_BY_KIND[kind], filename, limits=limits
        )
    if kind == XLSX_KIND and text.strip() == f"File: {filename}":
        # The upload extractor always leads with the file name; a workbook
        # with nothing else in it must still count as empty.
        return ""
    return text


async def extract_sharepoint_content(
    payload: bytes,
    content_type: str,
    filename: str,
    *,
    charset: Optional[str] = None,
    limits: Optional[FileExtractionLimits] = None,
) -> ExtractionResult:
    """Turn a complete download into text, a skip reason or a failure.

    ``charset`` is the one announced by the HTTP response, used for text
    formats only.
    """
    limits = limits or get_file_extraction_limits()
    mime = _base_mime(content_type)

    reason = unsupported_file_reason(filename)
    if reason:
        return ExtractionResult.skipped(reason, content_type)

    kind = detect_content_type(content_type, filename)
    if kind == UNSUPPORTED_KIND:
        label = _unsupported_content_type_label(mime) or _extension(filename) or mime
        return ExtractionResult.skipped(unsupported_type_reason(label), content_type)

    if not payload:
        return ExtractionResult.no_text(EMPTY_CONTENT_REASON, content_type)

    if kind in (TEXT_KIND, UNKNOWN_KIND):
        if _looks_binary(payload):
            label = _extension(filename) or mime or "binary"
            return ExtractionResult.skipped(
                unsupported_type_reason(label), content_type
            )
        text = _decode_text(payload, charset)
        if len(text.encode("utf-8")) > limits.max_output_bytes:
            return ExtractionResult.skipped(
                extraction_limit_reason(f"{limits.max_output_bytes} bytes of text"),
                content_type,
            )
    else:
        try:
            text = await _parse_in_sandbox(kind, payload, filename, limits)
        except PdfPageLimitError:
            return ExtractionResult.skipped(
                extraction_limit_reason(f"{limits.max_pdf_pages} PDF pages"),
                content_type,
            )
        except ExtractionLimitError as e:
            # The child exits with one status for memory, CPU, archive and
            # output caps alike, so the reason names the sandbox's limit.
            return ExtractionResult.skipped(
                extraction_limit_reason(e.limit), content_type
            )
        except EncryptedFileError:
            return ExtractionResult.error(PASSWORD_PROTECTED_REASON, content_type)
        except CorruptFileError:
            return ExtractionResult.error(CORRUPT_FILE_REASON, content_type)
        except UnsupportedFormatError:
            label = _extension(filename) or mime or "binary"
            return ExtractionResult.skipped(
                unsupported_type_reason(label), content_type
            )
        except ExtractionError as e:
            return ExtractionResult.error(e.message, content_type)
        except Exception as e:
            logger.error(f"Unexpected extraction error for '{filename}': {e}")
            return ExtractionResult.error(
                f"{type(e).__name__} while extracting {kind}", content_type
            )

    text = TextSanitizer.sanitize(text).strip()
    if not text:
        # A PDF whose pages carry no characters is the scanned-document case;
        # other formats with nothing in them are simply empty.
        reason = NO_TEXT_LAYER_REASON if kind == PDF_KIND else EMPTY_CONTENT_REASON
        return ExtractionResult.no_text(reason, content_type)
    return ExtractionResult.ok(text, content_type)


def get_metadata_from_sharepoint_item(item: SharePointItem) -> dict[str, Any]:
    """
    Extract useful metadata from a SharePoint item.

    Args:
        item: SharePoint item data

    Returns:
        Dictionary of metadata
    """
    metadata: dict[str, Any] = {
        "id": item.get("id", ""),
        "name": item.get("name", ""),
        "type": "folder"
        if item.get("folder")
        else file_extension_to_type(item.get("name", "")),
        "web_url": item.get("webUrl", ""),
        "created_by": item.get("createdBy", {}).get("user", {}).get("displayName", ""),
        "created_at": item.get("createdDateTime", ""),
        "modified_by": item.get("lastModifiedBy", {})
        .get("user", {})
        .get("displayName", ""),
        "modified_at": item.get("lastModifiedDateTime", ""),
    }

    # Add folder-specific metadata
    if item.get("folder"):
        metadata["child_count"] = item.get("folder", {}).get("childCount", 0)

    # Add file-specific metadata
    if item.get("file"):
        metadata["size"] = item.get("size", 0)
        metadata["mime_type"] = item.get("file", {}).get("mimeType", "")

    return metadata
