"""An uploaded template is a bounded, macro-free Word archive with a .docx name."""

import io
import zipfile

import pytest

from eneo.document_templates.validation import (
    MAX_TEMPLATE_BYTES,
    validate_template_archive,
    validate_template_filename,
)
from eneo.main.exceptions import BadRequestException, FileNotSupportedException


def _docx(extra: dict[str, bytes] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_filename_keeps_the_basename_and_requires_docx():
    assert (
        validate_template_filename("C:\\mallar\\Rapport mall.docx")
        == "Rapport mall.docx"
    )
    with pytest.raises(FileNotSupportedException):
        validate_template_filename("mall.docm")
    with pytest.raises(FileNotSupportedException):
        validate_template_filename("mall.pdf")
    with pytest.raises(BadRequestException):
        validate_template_filename(".docx")


def test_archive_checks_parts_macros_bounds_and_integrity():
    metrics = validate_template_archive(_docx())
    assert metrics.entry_count == 2
    with pytest.raises(BadRequestException):
        validate_template_archive(b"not a zip")
    with pytest.raises(BadRequestException):
        validate_template_archive(b"PK" + b"\0" * 10)
    with pytest.raises(FileNotSupportedException):
        validate_template_archive(_docx({"word/vbaProject.bin": b"x"}))
    with pytest.raises(BadRequestException):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", "<w:document/>")
        validate_template_archive(buffer.getvalue())
    with pytest.raises(BadRequestException):
        validate_template_archive(b"x" * (MAX_TEMPLATE_BYTES + 1))
