from __future__ import annotations

import io
import zipfile

from intric.files.text import (
    CorruptFileError,
    EncryptedFileError,
    ExtractionError,
    UnsupportedFormatError,
)
from intric.main.exceptions import BadRequestException, FileNotSupportedException

_DOCX_MACRO_SUFFIXES = (".docm", ".dotm")
_MAX_TEMPLATE_ARCHIVE_ENTRIES = 2048
_MAX_TEMPLATE_UNCOMPRESSED_BYTES = 50 * 1024 * 1024


def validate_template_extension(*, filename: str) -> None:
    lower_name = filename.casefold()
    if lower_name.endswith(_DOCX_MACRO_SUFFIXES):
        raise FileNotSupportedException(
            "Macro-enabled Word files are not allowed as flow templates.",
            code="flow_template_macro_not_allowed",
        )
    if not lower_name.endswith(".docx"):
        raise FileNotSupportedException(
            "Only .docx files can be uploaded as flow templates.",
            code="flow_template_unsupported_extension",
        )


def validate_docx_template_archive(template_bytes: bytes, *, filename: str) -> None:
    validate_template_extension(filename=filename)
    try:
        archive = zipfile.ZipFile(io.BytesIO(template_bytes))
    except zipfile.BadZipFile as exc:
        raise BadRequestException(
            "The uploaded file is not a valid DOCX archive.",
            code="flow_template_invalid_archive",
        ) from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > _MAX_TEMPLATE_ARCHIVE_ENTRIES:
            raise BadRequestException(
                "The uploaded DOCX archive contains too many entries.",
                code="flow_template_too_large",
            )
        total_uncompressed = sum(info.file_size for info in infos)
        if total_uncompressed > _MAX_TEMPLATE_UNCOMPRESSED_BYTES:
            raise BadRequestException(
                "The uploaded DOCX archive is too large when unpacked.",
                code="flow_template_too_large",
            )
        if archive.testzip() is not None:
            raise BadRequestException(
                "The uploaded DOCX archive is corrupted.",
                code="flow_template_corrupted_archive",
            )

        names = {info.filename for info in infos}
        if "[Content_Types].xml" not in names or "word/document.xml" not in names:
            raise BadRequestException(
                "The uploaded file is missing required DOCX parts.",
                code="flow_template_missing_required_parts",
            )
        if any(name.casefold().endswith("vbaproject.bin") for name in names):
            raise FileNotSupportedException(
                "Macro-enabled Word files are not allowed as flow templates.",
                code="flow_template_macro_not_allowed",
            )


def normalize_template_extraction_error(exc: Exception) -> Exception:
    if isinstance(exc, (BadRequestException, FileNotSupportedException)):
        return exc
    if isinstance(exc, (EncryptedFileError, UnsupportedFormatError)):
        return BadRequestException(
            "The DOCX template is unsupported or password-protected.",
            code="flow_template_invalid_archive",
        )
    if isinstance(exc, CorruptFileError):
        return BadRequestException(
            "The uploaded DOCX template is corrupted.",
            code="flow_template_corrupted_archive",
        )
    if isinstance(exc, ExtractionError):
        return BadRequestException(
            "The DOCX template could not be read.",
            code="flow_template_invalid_archive",
        )
    return BadRequestException(
        "The DOCX template could not be read.",
        code="flow_template_invalid_archive",
    )
