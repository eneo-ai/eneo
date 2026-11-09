import logging
import zipfile
from collections.abc import Iterable, Iterator
from enum import Enum
from pathlib import Path
from typing import Any, cast

import magic
import pdfplumber
import pptx
from docx2python import docx2python
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfminer.pdfparser import PDFSyntaxError
from pptx.exc import PackageNotFoundError

from eneo.files.extraction_limits import (
    FileExtractionLimits,
    get_file_extraction_limits,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Custom Exceptions
# =============================================================================


class ExtractionError(Exception):
    """Base exception for text extraction failures.

    An error names what went wrong, never the file: its message is logged and
    returned to the client, and a file's name is often what it is about, which
    retention removes with the file. Nor does it carry a parser's own text,
    which can quote the file's content.
    """

    def __init__(self, message: str, code: str = "EXTRACTION_FAILED"):
        self.message = message
        self.code = code
        super().__init__(self.message)


class NoExtractableTextError(ExtractionError):
    """Raised when extraction or transcription produces no usable text."""

    def __init__(self) -> None:
        super().__init__("The file contains no extractable text", "NO_EXTRACTABLE_TEXT")


class ExtractionLimitError(ExtractionError):
    def __init__(self, limit: str):
        self.limit = limit
        super().__init__(f"The file exceeded the {limit}", "EXTRACTION_LIMIT")


class PdfPageLimitError(ExtractionLimitError):
    def __init__(self, max_pages: int):
        super().__init__(f"PDF page limit ({max_pages} pages)")


class EncryptedFileError(ExtractionError):
    """Raised for password-protected files."""

    def __init__(self) -> None:
        super().__init__("The file is encrypted/password-protected", "ENCRYPTED")


class CorruptFileError(ExtractionError):
    """Raised for corrupted or malformed files."""

    def __init__(self, details: str = ""):
        message = "The file is corrupted or malformed"
        if details:
            message = f"{message}. {details}"
        super().__init__(message, "CORRUPT")


class UnsupportedFormatError(ExtractionError):
    """Raised for unsupported file formats."""

    def __init__(self, format_type: str):
        super().__init__(
            f"Format '{format_type}' not supported. "
            "Please convert the file to a supported format.",
            "UNSUPPORTED_FORMAT",
        )


# =============================================================================
# MIME Types
# =============================================================================


class MimeTypesBase(str, Enum):
    @classmethod
    def has_value(cls, value: str) -> bool:
        base_value = value.split(";")[0].strip()
        return any(base_value == item.value for item in cls)

    @classmethod
    def values(cls) -> list[str]:
        return [item.value for item in cls]


class TextMimeTypes(MimeTypesBase):
    # Text formats the extractor can handle. Doubles as the upload/attachment
    # allowlist (see limits.limit_service). The crawler maintains its own
    # download policy in crawler.parse_html.CRAWLABLE_DOCUMENT_MIMETYPES — keep
    # the two concerns separate so changing one never silently affects the other.
    # Supported formats
    MD = "text/markdown"
    TXT = "text/plain"
    PDF = "application/pdf"
    DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    TEXT_CSV = "text/csv"
    APP_CSV = "application/csv"
    PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    XLS = "application/vnd.ms-excel"
    JSON = "application/json"
    # Browsers and libmagic disagree on the XML mimetype, so accept both spellings
    XML = "text/xml"
    XML_APP = "application/xml"

    # Legacy formats (for detection/rejection only)
    DOC = "application/msword"
    PPT = "application/vnd.ms-powerpoint"


# =============================================================================
# Text Processing
# =============================================================================


class TextSanitizer:
    @staticmethod
    def sanitize(text: str) -> str:
        text = text.replace("\x00", "")
        return text


def _log_read_error(error: OSError) -> None:
    # The error's message holds the path, so only its type and errno.
    logger.warning(
        "Reading a file for extraction failed (%s, errno %s)",
        type(error).__name__,
        error.errno,
    )


class TextExtractor:
    @staticmethod
    def _looks_binary(filepath: Path) -> bool:
        # A NUL byte in the leading chunk reliably marks binary content
        # (images, video, archives); UTF-8/cp1252 text never contains it.
        try:
            with open(filepath, "rb") as f:
                return b"\x00" in f.read(8192)
        except (PermissionError, OSError):
            return False

    @staticmethod
    def extract_from_plain_text(filepath: Path) -> str:
        # Try UTF-8 first, then cp1252 (Windows), then UTF-8 with replacement
        # Avoid latin-1 as it accepts any byte sequence including binary garbage
        try:
            return filepath.read_text("utf-8")
        except UnicodeDecodeError:
            pass
        except PermissionError as e:
            _log_read_error(e)
            raise ExtractionError("Permission denied reading the file") from None
        except OSError as e:
            _log_read_error(e)
            raise ExtractionError("Error reading the file") from None

        try:
            return filepath.read_text("cp1252")
        except UnicodeDecodeError:
            pass

        # Final fallback: UTF-8 with replacement characters for undecodable bytes
        try:
            return filepath.read_text("utf-8", errors="replace")
        except OSError as e:
            _log_read_error(e)
            raise ExtractionError("Error reading the file") from None

    @staticmethod
    def _table_to_markdown(table: list[list[str | None]]) -> str:
        rows = [
            [(cell or "").replace("\n", " ").strip() for cell in row]
            for row in table
            if any(cell for cell in row)
        ]
        if not rows:
            return ""

        lines = ["| " + " | ".join(rows[0]) + " |"]
        lines.append("| " + " | ".join("---" for _ in rows[0]) + " |")
        for row in rows[1:]:
            # Pad short rows so the markdown stays rectangular
            padded = row + [""] * (len(rows[0]) - len(row))
            lines.append("| " + " | ".join(padded[: len(rows[0])]) + " |")
        return "\n".join(lines)

    @classmethod
    def _extract_pdf_page(cls, page: Any) -> str:
        # pdfplumber ships no type stubs — treat the page as Any and pin the
        # types we rely on at the boundaries.
        tables: list[Any] = list(page.find_tables())
        if not tables:
            return str(page.extract_text() or "")

        # Extract running text outside the table regions, then append the
        # tables as markdown — otherwise table cells appear twice.
        table_bboxes: list[tuple[float, float, float, float]] = [
            tuple(table.bbox) for table in tables
        ]

        def outside_tables(obj: dict[str, Any]) -> bool:
            center_x = (float(obj["x0"]) + float(obj["x1"])) / 2
            center_y = (float(obj["top"]) + float(obj["bottom"])) / 2
            return not any(
                x0 <= center_x <= x1 and top <= center_y <= bottom
                for (x0, top, x1, bottom) in table_bboxes
            )

        parts: list[str] = []
        text = str(page.filter(outside_tables).extract_text() or "")
        if text.strip():
            parts.append(text)
        for table in tables:
            markdown = cls._table_to_markdown(table.extract())
            if markdown:
                parts.append(markdown)
        return "\n\n".join(parts)

    @classmethod
    def _layout_page_texts(cls, pdf: Any) -> Iterator[str]:
        for page in pdf.pages:
            try:
                try:
                    page_text = cls._extract_pdf_page(page)
                except Exception as e:
                    logger.warning(
                        "Table-aware extraction failed on page %s (%s), "
                        "falling back to plain text",
                        page.page_number,
                        type(e).__name__,
                    )
                    page_text = str(page.extract_text() or "")
            finally:
                # pdfplumber keeps every parsed page's objects alive until the
                # document closes; releasing them per page keeps memory flat
                # instead of growing by megabytes per page.
                page.close()
            yield page_text

    @staticmethod
    def _text_layer_page_texts(filepath: Path) -> Iterator[str]:
        import pypdfium2  # pyright: ignore[reportMissingTypeStubs]  # no stubs published

        document: Any = pypdfium2.PdfDocument(filepath)
        try:
            for index in range(len(document)):
                page = document[index]
                try:
                    text_page = page.get_textpage()
                    try:
                        text = str(text_page.get_text_bounded())
                    finally:
                        text_page.close()
                finally:
                    page.close()
                # PDFium ends lines with CRLF and marks a hyphen that breaks a
                # word across lines as U+0002; write both the way the layout
                # path does.
                yield text.replace("\r\n", "\n").replace("\x02", "-\n")
        finally:
            document.close()

    @classmethod
    def extract_from_pdf(
        cls,
        filepath: Path,
        *,
        limits: FileExtractionLimits | None = None,
    ) -> str:
        try:
            with pdfplumber.open(filepath) as pdf:
                page_count = len(pdf.pages)
                if limits is not None and page_count > limits.max_pdf_pages:
                    raise PdfPageLimitError(limits.max_pdf_pages)
                layout_max_pages = (
                    limits or get_file_extraction_limits()
                ).pdf_layout_max_pages
                if page_count > layout_max_pages:
                    logger.info(
                        f"PDF has {page_count} pages (over "
                        f"{layout_max_pages}); reading its text layer without "
                        "table detection"
                    )
                    texts = cls._text_layer_page_texts(filepath)
                else:
                    texts = cls._layout_page_texts(pdf)

                page_texts: list[str] = []
                output_bytes = 0
                has_content = False
                for page_number, page_text in enumerate(texts, start=1):
                    has_content = has_content or bool(page_text.strip())
                    marked_text = f"[PAGE {page_number}]\n{page_text}"
                    output_bytes += len(marked_text.encode("utf-8")) + (
                        2 if page_texts else 0
                    )
                    if limits is not None and output_bytes > limits.max_output_bytes:
                        raise ExtractionLimitError("text output limit")
                    page_texts.append(marked_text)

                extracted_text = "\n\n".join(page_texts)

            # Warn if no text extracted (likely image-only/scanned PDF)
            if not has_content:
                logger.warning(
                    "No text extracted from PDF - file may be image-only or scanned"
                )
                # Return empty rather than bare page markers, so downstream
                # empty-content handling keeps working.
                return ""

            return TextSanitizer.sanitize(extracted_text)

        except ExtractionLimitError:
            raise
        except PDFPasswordIncorrect as e:
            logger.warning("Password-protected PDF rejected")
            raise EncryptedFileError() from e
        except PDFSyntaxError:
            logger.warning("PDF read error")
            raise CorruptFileError() from None
        except Exception as e:
            logger.error("Unexpected PDF extraction error (%s)", type(e).__name__)
            raise ExtractionError("PDF extraction failed") from None

    @staticmethod
    def extract_from_docx(filepath: Path) -> str:
        try:
            with docx2python(filepath) as docx_content:
                return docx_content.text
        except zipfile.BadZipFile:
            raise CorruptFileError(
                "Invalid ZIP structure - file may be corrupted or in legacy .doc format",
            ) from None
        except KeyError:
            raise CorruptFileError("Missing required document component") from None
        except Exception as e:
            logger.error("Unexpected DOCX extraction error (%s)", type(e).__name__)
            raise ExtractionError("DOCX extraction failed") from None

    @staticmethod
    def extract_from_xlsx(filepath: Path, filename: str | None = None) -> str:
        import pandas as pd

        display_name = filename or filepath.name
        try:
            # pandas-stubs miss the context-manager protocol on ExcelFile, so
            # close() explicitly to avoid leaking the underlying file handle.
            xls = pd.ExcelFile(filepath, engine="calamine")
            try:
                parts: list[str] = []

                # Global file context (helpful for first chunk and direct chat)
                parts.append(f"File: {display_name}")

                for sheet_name in xls.sheet_names:
                    df: pd.DataFrame = pd.read_excel(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]  # pandas stubs are incomplete
                        xls, sheet_name=sheet_name, engine="calamine"
                    )

                    # Clean column names (ensure strings, remove newlines)
                    df.columns = (  # pyright: ignore[reportUnknownMemberType]  # pandas stubs are incomplete
                        df.columns.astype(str).str.replace("\n", " ")  # pyright: ignore[reportUnknownMemberType]  # pandas stubs are incomplete
                    )

                    if df.empty:  # pyright: ignore[reportUnknownMemberType]  # pandas stubs are incomplete
                        # The first row is the header; a sheet holding only
                        # that row (a list of names, say) is still text.
                        column_names = [
                            str(name)
                            for name in cast(
                                Iterable[object],
                                df.columns,  # pyright: ignore[reportUnknownMemberType]  # pandas stubs are incomplete
                            )
                        ]
                        headers = [
                            name
                            for name in column_names
                            if not name.startswith("Unnamed: ")
                        ]
                        if headers:
                            parts.append(
                                f"Sheet: {sheet_name} | headers: " + " | ".join(headers)
                            )
                        continue

                    # Handle merged cells - forward fill values
                    df = df.ffill()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]  # pandas stubs are incomplete

                    # Serialize each row as self-contained key-value pairs
                    # This ensures every chunk has full context, even if split
                    def serialize_row(row: pd.Series) -> str:  # type: ignore[type-arg]  # pd.Series generic param unavailable at runtime
                        # Filter out NaN to save tokens
                        pairs = [
                            f"{col}: {val}"
                            for col, val in row.items()
                            if pd.notna(val)  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]  # pandas stubs are incomplete
                        ]
                        return f"Sheet: {sheet_name} | " + " | ".join(pairs)

                    # pandas apply/str.cat return types are unknown due to incomplete stubs
                    raw_sheet_text = df.apply(serialize_row, axis=1).str.cat(sep="\n")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]  # pandas stubs are incomplete
                    sheet_text: str = str(raw_sheet_text)  # pyright: ignore[reportUnknownArgumentType]  # pandas stubs are incomplete
                    parts.append(sheet_text)

                return "\n\n".join(parts)
            finally:
                xls.close()  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]  # pandas-stubs miss ExcelFile.close
        except ValueError:
            raise CorruptFileError("Cannot parse Excel format") from None
        except Exception as e:
            logger.error("Unexpected Excel extraction error (%s)", type(e).__name__)
            raise ExtractionError("Excel extraction failed") from None

    @staticmethod
    def extract_from_pptx(filepath: Path) -> str:
        try:
            # Extract text from pptx using python-pptx
            # Use list join instead of string concatenation for O(n) vs O(n^2) complexity
            # pptx.Presentation accepts str, not Path — convert explicitly
            presentation = pptx.Presentation(str(filepath))
            parts: list[str] = []
            for slide in presentation.slides:
                slide_parts: list[str] = []
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        # Collect all text from runs in this shape
                        # python-pptx stubs are incomplete; member types are partially unknown
                        shape_text = " ".join(
                            run.text  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]  # pptx stubs are incomplete
                            for para in shape.text_frame.paragraphs  # type: ignore[attr-defined]
                            for run in para.runs  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]  # pptx stubs are incomplete
                            if run.text  # pyright: ignore[reportUnknownMemberType]  # pptx stubs are incomplete
                        )
                        if shape_text.strip():
                            slide_parts.append(shape_text)
                if slide.has_notes_slide:
                    notes_frame = slide.notes_slide.notes_text_frame  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType, reportOptionalMemberAccess]  # pptx stubs are incomplete
                    notes_text = (
                        (notes_frame.text or "").strip()
                        if notes_frame is not None
                        else ""
                    )  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]  # pptx stubs are incomplete
                    if notes_text:
                        slide_parts.append(f"Speaker notes: {notes_text}")
                if slide_parts:
                    parts.append(" ".join(slide_parts))
            return "\n".join(parts)
        except (zipfile.BadZipFile, PackageNotFoundError):
            raise CorruptFileError(
                "Invalid ZIP structure - file may be corrupted or in legacy .ppt format",
            ) from None
        except KeyError:
            raise CorruptFileError("Missing required presentation component") from None
        except Exception as e:
            logger.error("Unexpected PPTX extraction error (%s)", type(e).__name__)
            raise ExtractionError("PPTX extraction failed") from None

    @staticmethod
    def _reject_legacy_format(mimetype: str | None) -> None:
        if mimetype == TextMimeTypes.DOC.value:
            raise UnsupportedFormatError(".doc (Legacy Word) - please save as .docx")
        if mimetype == TextMimeTypes.PPT.value:
            raise UnsupportedFormatError(
                ".ppt (Legacy PowerPoint) - please save as .pptx"
            )

    def extract(
        self,
        filepath: Path,
        mimetype: str | None = None,
        filename: str | None = None,
        *,
        limits: FileExtractionLimits | None = None,
    ) -> str:
        mimetype = mimetype or magic.from_file(filepath, mime=True)  # pyright: ignore[reportUnknownMemberType]  # python-magic stubs are incomplete
        self._reject_legacy_format(mimetype)

        match mimetype:
            case (
                TextMimeTypes.TXT
                | TextMimeTypes.MD
                | TextMimeTypes.TEXT_CSV
                | TextMimeTypes.APP_CSV
                | TextMimeTypes.JSON
                | TextMimeTypes.XML
                | TextMimeTypes.XML_APP
            ):
                extracted_text = self.extract_from_plain_text(filepath)
            case TextMimeTypes.PDF:
                extracted_text = self.extract_from_pdf(filepath, limits=limits)
            case TextMimeTypes.DOCX:
                extracted_text = self.extract_from_docx(filepath)
            case TextMimeTypes.PPTX:
                extracted_text = self.extract_from_pptx(filepath)
            case TextMimeTypes.XLSX | TextMimeTypes.XLS:
                # The workbook's name heads its text, as context for its chunks.
                extracted_text = self.extract_from_xlsx(
                    filepath, filename or filepath.name
                )
            case _:
                # Unknown mimetype: only treat as text if it is not binary.
                # Guards against binary uploads (e.g. unsupported image formats)
                # being decoded into garbage and written to the TEXT column.
                if self._looks_binary(filepath):
                    raise UnsupportedFormatError(mimetype or "binary")
                extracted_text = self.extract_from_plain_text(filepath)

        return extracted_text.strip()

    async def extract_bounded(
        self,
        filepath: Path,
        mimetype: str | None = None,
        filename: str | None = None,
        *,
        limits: FileExtractionLimits | None = None,
    ) -> str:
        from eneo.files.bounded_extraction import extract_in_process

        # The child reports failures as an exit status, so the conversion
        # hint for legacy formats is raised here, before it is spawned.
        self._reject_legacy_format(mimetype)
        return await extract_in_process(
            filepath, mimetype, filename or filepath.name, limits=limits
        )
