"""Cheap checks on an uploaded Word template before anything reads it.

The archive is bounded and inspected by name only; the tool runtime, in its
sandbox, is what parses the parts. The same rules apply to Flows' template
assets, so a template rejected here is rejected there.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

from eneo.main.exceptions import BadRequestException, FileNotSupportedException

_MACRO_SUFFIXES = (".docm", ".dotm")
MAX_TEMPLATE_BYTES = 5 * 1024 * 1024
MAX_TEMPLATE_ARCHIVE_ENTRIES = 2048
MAX_TEMPLATE_UNCOMPRESSED_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class TemplateArchiveMetrics:
    entry_count: int
    uncompressed_bytes: int


def validate_template_filename(filename: str) -> str:
    """The file name a template is stored under: a .docx, without path parts."""
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    lower = name.casefold()
    if lower.endswith(_MACRO_SUFFIXES):
        raise FileNotSupportedException(
            "Macro-enabled Word files cannot be used as document templates."
        )
    if not lower.endswith(".docx"):
        raise FileNotSupportedException(
            "Only .docx files can be uploaded as document templates."
        )
    if len(name) > 255 or len(name) <= len(".docx"):
        raise BadRequestException(
            "The template needs a file name of at most 255 characters."
        )
    return name


def validate_template_archive(template_bytes: bytes) -> TemplateArchiveMetrics:
    if len(template_bytes) > MAX_TEMPLATE_BYTES:
        raise BadRequestException("A document template may be at most 5 MiB.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(template_bytes))
    except zipfile.BadZipFile as exc:
        raise BadRequestException(
            "The uploaded file is not a valid Word (.docx) archive."
        ) from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_TEMPLATE_ARCHIVE_ENTRIES:
            raise BadRequestException(
                "The uploaded Word archive contains too many entries."
            )
        total = sum(info.file_size for info in infos)
        if total > MAX_TEMPLATE_UNCOMPRESSED_BYTES:
            raise BadRequestException(
                "The uploaded Word archive is too large when unpacked."
            )
        names = {info.filename for info in infos}
        if "[Content_Types].xml" not in names or "word/document.xml" not in names:
            raise BadRequestException(
                "The uploaded file is missing required Word parts."
            )
        if any(name.casefold().endswith("vbaproject.bin") for name in names):
            raise FileNotSupportedException(
                "Macro-enabled Word files cannot be used as document templates."
            )
        if archive.testzip() is not None:
            raise BadRequestException("The uploaded Word archive is corrupted.")
        return TemplateArchiveMetrics(entry_count=len(infos), uncompressed_bytes=total)
