"""Which synced originals are kept, and the schema stub for unreadable workbooks.

A synced document normally survives only as extracted text. Tabular files are
the exception: a spreadsheet's value lies in computing over it, which needs
the bytes, so their originals are retained and handed to analysis tools as
signed references. This module is the one place that decides which files
that applies to.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator, Mapping
from typing import Any

# Extension -> media type of the originals a sync keeps. Growing this list is
# the whole change needed to hand another kind of file to tools.
RETAINED_ORIGINALS: Mapping[str, str] = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "tsv": "text/tab-separated-values",
}
_EXTENSION_BY_MEDIA_TYPE = {media: ext for ext, media in RETAINED_ORIGINALS.items()}
PLACEHOLDER_MAX_CHARS = 2000
_PLACEHOLDER_MAX_SHEETS = 20


def _extension(filename: str) -> str:
    name = filename.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def original_media_type(filename: str, content_type: str | None = None) -> str | None:
    """The media type to store the original under, or None when it is not kept.

    The file name decides; the response header only helps when the name has
    no extension.
    """
    extension = _extension(filename)
    if extension:
        return RETAINED_ORIGINALS.get(extension)
    if content_type:
        base = content_type.split(";", 1)[0].strip().lower()
        if base in _EXTENSION_BY_MEDIA_TYPE:
            return base
    return None


def retain_original_bytes(filename: str, content_type: str | None = None) -> bool:
    return original_media_type(filename, content_type) is not None


def build_tabular_placeholder_text(filename: str, data: bytes) -> str:
    """Title, sheet names and header rows of a table whose text was not extracted.

    Indexed in place of the rows, so search still finds the file by name or
    column and the table tools open the original.
    """
    lines = [
        f"Spreadsheet: {filename}",
        "Row text could not be extracted; the file is available to the table "
        "analysis tools.",
        "",
    ]
    try:
        for sheet, columns in _sheet_headers(filename, data):
            header = ", ".join(str(column) for column in columns) or "(no header row)"
            lines.append(
                f'Sheet "{sheet}": {header}' if sheet else f"Columns: {header}"
            )
    except Exception:  # noqa: BLE001 - a header preview must never fail a sync
        lines.append("(column headers could not be read)")
    return "\n".join(lines)[:PLACEHOLDER_MAX_CHARS]


def _sheet_headers(
    filename: str, data: bytes
) -> Iterator[tuple[str | None, list[str]]]:
    if _extension(filename) == "xlsx":
        import pandas

        # Same reader as the text extractors (calamine ships with the service;
        # openpyxl is a test-only dependency). pandas-stubs do not type the
        # ExcelFile-based calls, so go through an untyped handle.
        pd: Any = pandas
        xls = pd.ExcelFile(io.BytesIO(data), engine="calamine")
        try:
            for sheet in list(xls.sheet_names)[:_PLACEHOLDER_MAX_SHEETS]:
                frame = pd.read_excel(
                    xls, sheet_name=sheet, header=None, nrows=1, engine="calamine"
                )
                first_row = [] if frame.empty else list(frame.iloc[0])
                yield str(sheet), [str(cell) for cell in first_row if pd.notna(cell)]
        finally:
            xls.close()
        return
    delimiter = "\t" if _extension(filename) == "tsv" else ","
    first_line = (
        data.split(b"\n", 1)[0].decode("utf-8", errors="replace").lstrip("\ufeff")
    )
    no_header: list[str] = []
    yield None, next(csv.reader([first_line], delimiter=delimiter), no_header)
