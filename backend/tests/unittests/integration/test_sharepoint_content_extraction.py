"""Bytes downloaded from SharePoint become text, a skip reason or a failure."""

import json
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from eneo.files.extraction_limits import FileExtractionLimits
from eneo.files.text import EncryptedFileError, TextExtractor
from eneo.integration.infrastructure.content_service.parsing import (
    unsupported_file_reason,
)
from eneo.integration.infrastructure.content_service.utils import (
    DOCX_KIND,
    EMPTY_CONTENT_REASON,
    NO_TEXT_LAYER_REASON,
    NO_TEXT_REASONS,
    PDF_KIND,
    PPTX_KIND,
    TEXT_KIND,
    UNKNOWN_KIND,
    UNSUPPORTED_KIND,
    XLSX_KIND,
    ExtractionResult,
    detect_content_type,
    extract_sharepoint_content,
    file_too_large_reason,
    is_unextractable_content,
)
from tests.unittests.integration.sharepoint_fixtures import (
    DOCX_MIME,
    OCTET,
    PPTX_MIME,
    XLSX_MIME,
    docx_bytes,
    header_only_xlsx_bytes,
    pdf_bytes,
    pptx_bytes,
    xlsx_bytes,
)


class TestSupportedFormats:
    @pytest.mark.parametrize(
        ("filename", "content_type", "build", "expected"),
        [
            (
                "report.docx",
                DOCX_MIME,
                lambda t: docx_bytes("Budget 2026"),
                "Budget 2026",
            ),
            ("report.docx", OCTET, lambda t: docx_bytes("Octet body"), "Octet body"),
            (
                "numbers.xlsx",
                XLSX_MIME,
                lambda t: xlsx_bytes([["Name", "Value"], ["Rent", 100]]),
                "Name: Rent | Value: 100",
            ),
            (
                "names.xlsx",
                XLSX_MIME,
                lambda t: header_only_xlsx_bytes(),
                "Sheet: Budget | headers: Name | Value",
            ),
            ("deck.pptx", PPTX_MIME, lambda t: pptx_bytes("Roadmap Q3"), "Roadmap Q3"),
            (
                "scan.pdf",
                "application/pdf",
                lambda t: pdf_bytes(["Hello PDF"]),
                "[PAGE 1]\nHello PDF",
            ),
            ("notes.txt", "text/plain", lambda t: "Plain text".encode(), "Plain text"),
            ("data.csv", "text/csv", lambda t: b"a,b\n1,2", "a,b\n1,2"),
            ("readme.md", OCTET, lambda t: b"# Title", "# Title"),
            (
                "payload.json",
                "application/json",
                lambda t: json.dumps({"k": 1}).encode(),
                '{"k": 1}',
            ),
            (
                "README",
                "text/plain; charset=utf-8",
                lambda t: "Ingen ändelse".encode(),
                "Ingen ändelse",
            ),
        ],
    )
    def test_extracts_text_with_the_upload_parsers(
        self,
        tmp_path: Path,
        filename: str,
        content_type: str,
        build: Callable[[Path], bytes],
        expected: str,
    ):
        result = extract_sharepoint_content(build(tmp_path), content_type, filename)

        assert result.failed is False
        assert result.skip_reason is None
        assert result.text is not None and expected in result.text
        assert result.content_type == content_type

    @pytest.mark.parametrize(
        ("payload", "charset", "expected"),
        [
            ("café".encode("utf-8"), None, "café"),
            ("café".encode("cp1252"), None, "café"),
            ("café".encode("latin-1"), "iso-8859-1", "café"),
            ("café".encode("utf-16"), None, "café"),
        ],
        ids=["utf8", "cp1252-fallback", "declared-latin1", "utf16-bom"],
    )
    def test_decodes_text_by_charset_then_utf8_then_cp1252(
        self, payload: bytes, charset: str | None, expected: str
    ):
        result = extract_sharepoint_content(
            payload, "text/plain", "notes.txt", charset=charset
        )
        assert result.text == expected

    def test_null_bytes_are_stripped_before_storage(self):
        with patch.object(TextExtractor, "extract_from_docx", return_value="Hel\x00lo"):
            result = extract_sharepoint_content(b"PK", DOCX_MIME, "a.docx")
        assert result.text == "Hello"


class TestNoTextIsNotAFailure:
    def test_scanned_pdf_reports_missing_text_layer(self):
        result = extract_sharepoint_content(
            pdf_bytes(["", ""]), "application/pdf", "scan.pdf"
        )

        assert result == ExtractionResult(
            skip_reason=NO_TEXT_LAYER_REASON, content_type="application/pdf"
        )
        assert result.failed is False
        assert result.is_no_text is True

    @pytest.mark.parametrize(
        ("filename", "content_type", "payload"),
        [
            ("empty.docx", DOCX_MIME, docx_bytes()),
            ("empty.xlsx", XLSX_MIME, xlsx_bytes([])),
            ("empty.pptx", PPTX_MIME, pptx_bytes()),
            ("empty.txt", "text/plain", b"   \n"),
            ("zero-bytes.pdf", "application/pdf", b""),
        ],
        # Office payloads are generated at collection time and differ per
        # xdist worker (zip timestamps); the filename keeps ids stable.
        ids=["docx", "xlsx", "pptx", "txt", "pdf"],
    )
    def test_empty_documents_report_empty_content(
        self, filename: str, content_type: str, payload: bytes
    ):
        result = extract_sharepoint_content(payload, content_type, filename)

        assert result.skip_reason == EMPTY_CONTENT_REASON
        assert result.failed is False
        assert result.is_no_text is True

    def test_no_text_reasons_are_the_only_positive_outcomes(self):
        assert NO_TEXT_REASONS == {NO_TEXT_LAYER_REASON, EMPTY_CONTENT_REASON}
        assert ExtractionResult.error("x").is_no_text is False
        assert ExtractionResult.skipped("Unsupported file type (x)").is_no_text is False
        with pytest.raises(ValueError, match="no-text reason"):
            ExtractionResult.no_text("Error: Corrupt or malformed file")


class TestUnsupportedFormatsNeverProduceGarbage:
    # Bytes that the old byte scraper would have turned into "text".
    GARBAGE = (
        b"\xd0\xcf\x11\xe0"
        + b"\x00" * 16
        + b"Calibri"
        + b"\x00" * 4
        + b"xmlns:w=http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        + b"\x00" * 4
        + b"Times New Roman is a long enough run of printable characters"
    )

    @pytest.mark.parametrize(
        ("filename", "content_type", "label"),
        [
            ("old.doc", "application/msword", "legacy Word .doc, save as .docx"),
            ("old.doc", OCTET, "legacy Word .doc, save as .docx"),
            (
                "old.ppt",
                "application/vnd.ms-powerpoint",
                "legacy PowerPoint .ppt, save as .pptx",
            ),
            ("notes.one", "application/onenote", "OneNote"),
            ("mail.msg", "application/vnd.ms-outlook", "Outlook .msg"),
            ("memo.rtf", "text/rtf", "rich text .rtf"),
            ("memo.rtf", "application/rtf", "rich text .rtf"),
            (
                "text.odt",
                "application/vnd.oasis.opendocument.text",
                "OpenDocument .odt",
            ),
            ("sheet.ods", OCTET, "OpenDocument .ods"),
            ("slides.odp", OCTET, "OpenDocument .odp"),
            ("book.xlsb", OCTET, ".xlsb"),
            ("photo", "image/png", "image"),
            ("download", "application/msword", "legacy Word .doc, save as .docx"),
            ("download", "text/rtf", "rich text .rtf"),
            ("blob.dat", OCTET, ".dat"),
            ("blob", OCTET, "application/octet-stream"),
            ("blob", "", "binary"),
            ("looks-like-text.txt", "text/plain", ".txt"),
        ],
    )
    def test_reports_a_precise_unsupported_reason(
        self, filename: str, content_type: str, label: str
    ):
        result = extract_sharepoint_content(self.GARBAGE, content_type, filename)

        assert result.skip_reason == f"Unsupported file type ({label})"
        assert result.text is None
        assert result.failed is False
        assert result.is_no_text is False


class TestFailuresAreNotNoText:
    @pytest.mark.parametrize(
        ("filename", "content_type", "payload"),
        [
            ("corrupt.docx", DOCX_MIME, b"not a zip at all"),
            ("corrupt.pptx", PPTX_MIME, b"PK\x03\x04 truncated zip"),
            ("corrupt.xlsx", XLSX_MIME, b"PK\x03\x04 truncated zip"),
            ("corrupt.pdf", "application/pdf", b"%PDF-1.4 garbage without xref"),
        ],
    )
    def test_corrupt_files_fail_with_an_error_reason(
        self, filename: str, content_type: str, payload: bytes
    ):
        result = extract_sharepoint_content(payload, content_type, filename)

        assert result.failed is True
        assert result.text is None
        assert result.skip_reason is not None
        assert result.skip_reason.startswith("Error: ")
        assert result.is_no_text is False

    def test_encrypted_pdf_fails(self):
        with patch.object(
            TextExtractor,
            "extract_from_pdf",
            side_effect=EncryptedFileError("locked.pdf"),
        ):
            result = extract_sharepoint_content(
                b"%PDF", "application/pdf", "locked.pdf"
            )

        assert result == ExtractionResult(
            skip_reason="Error: Password-protected file",
            failed=True,
            content_type="application/pdf",
        )

    def test_unexpected_parser_exception_fails(self):
        with patch.object(
            TextExtractor, "extract_from_docx", side_effect=RuntimeError("boom")
        ):
            result = extract_sharepoint_content(b"PK", DOCX_MIME, "a.docx")

        assert result.failed is True
        assert result.skip_reason == "Error: RuntimeError while extracting docx"


class TestExtractionLimits:
    def test_pdf_over_page_limit_is_skipped_not_chunked(self):
        limits = FileExtractionLimits(max_pdf_pages=2)

        result = extract_sharepoint_content(
            pdf_bytes(["one", "two", "three"]),
            "application/pdf",
            "long.pdf",
            limits=limits,
        )

        assert result.skip_reason == "Exceeds extraction limit (2 PDF pages)"
        assert result.failed is False
        assert result.is_no_text is False

    @pytest.mark.parametrize(
        ("filename", "content_type", "payload"),
        [
            ("big.docx", DOCX_MIME, docx_bytes("x" * 200)),
            ("big.txt", "text/plain", b"x" * 200),
        ],
        ids=["docx", "txt"],
    )
    def test_oversized_output_is_skipped(
        self, filename: str, content_type: str, payload: bytes
    ):
        limits = FileExtractionLimits(max_output_bytes=100)

        result = extract_sharepoint_content(
            payload, content_type, filename, limits=limits
        )

        assert result.skip_reason == "Exceeds extraction limit (100 bytes of text)"
        assert result.failed is False


class TestDispatch:
    @pytest.mark.parametrize(
        ("filename", "content_type", "kind"),
        [
            # A known extension wins over the header.
            ("report.docx", OCTET, DOCX_KIND),
            ("report.docx", "text/html", DOCX_KIND),
            ("report.pdf", "text/html", PDF_KIND),
            ("book.xls", "application/vnd.ms-excel", XLSX_KIND),
            ("macro.xlsm", OCTET, XLSX_KIND),
            ("deck.pptx", "", PPTX_KIND),
            ("notes.txt", OCTET, TEXT_KIND),
            # The header decides for unknown or missing extensions.
            ("download", "application/pdf; charset=binary", PDF_KIND),
            ("download", DOCX_MIME, DOCX_KIND),
            ("download", "application/vnd.ms-excel", XLSX_KIND),
            ("download", "text/plain; charset=utf-8", TEXT_KIND),
            ("download", "application/ld+json", TEXT_KIND),
            ("feed.atom", "application/atom+xml", TEXT_KIND),
            # Unsupported by either side.
            ("memo.rtf", "text/plain", UNSUPPORTED_KIND),
            ("photo", "image/jpeg", UNSUPPORTED_KIND),
            ("old.doc", DOCX_MIME, UNSUPPORTED_KIND),
            # Nothing known: decided by sniffing the bytes later.
            ("blob", OCTET, UNKNOWN_KIND),
            ("blob.dat", "", UNKNOWN_KIND),
        ],
    )
    def test_detect_content_type(self, filename: str, content_type: str, kind: str):
        assert detect_content_type(content_type, filename) == kind

    @pytest.mark.parametrize(
        ("filename", "reason"),
        [
            ("old.doc", "Unsupported file type (legacy Word .doc, save as .docx)"),
            (
                "old.PPT",
                "Unsupported file type (legacy PowerPoint .ppt, save as .pptx)",
            ),
            ("notes.one", "Unsupported file type (OneNote)"),
            ("mail.msg", "Unsupported file type (Outlook .msg)"),
            ("memo.rtf", "Unsupported file type (rich text .rtf)"),
            ("text.odt", "Unsupported file type (OpenDocument .odt)"),
            ("photo.jpg", "Unsupported file type (image)"),
            ("clip.mp4", "Unsupported file type (video)"),
            ("song.mp3", "Unsupported file type (audio)"),
            ("bundle.zip", "Unsupported file type (.zip)"),
            ("report.docx", None),
            ("book.xls", None),
            ("scan.pdf", None),
            ("README", None),
        ],
    )
    def test_unsupported_file_reason_is_decided_before_download(
        self, filename: str, reason: str | None
    ):
        assert unsupported_file_reason(filename) == reason


class TestExtractionResultInvariants:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {},
            {"text": "x", "skip_reason": "y"},
            {"text": "   "},
            {"text": "x", "failed": True},
        ],
    )
    def test_rejects_inconsistent_results(self, kwargs: dict[str, object]):
        with pytest.raises(ValueError):
            ExtractionResult(**kwargs)  # type: ignore[arg-type]

    def test_is_unextractable_content_is_an_empty_check(self):
        assert is_unextractable_content(None) is True
        assert is_unextractable_content("  \n\t ") is True
        assert is_unextractable_content("Real document content here.") is False


class TestFileTooLargeReason:
    @pytest.mark.parametrize(
        ("limit_bytes", "expected"),
        [
            (50 * 1024 * 1024, "File too large (exceeds 50 MB limit)"),
            (10 * 1024 * 1024, "File too large (exceeds 10 MB limit)"),
            (1536 * 1024, "File too large (exceeds 1.5 MB limit)"),
        ],
    )
    def test_names_the_configured_limit(self, limit_bytes, expected):
        assert file_too_large_reason(limit_bytes) == expected
