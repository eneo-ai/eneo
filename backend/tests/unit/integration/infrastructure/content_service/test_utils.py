"""Text synced spreadsheets are indexed under: whole while small, sampled when large."""

import io

from openpyxl import Workbook

from eneo.integration.infrastructure.content_service.utils import (
    extract_text_from_xlsx,
)


def _workbook(rows: int) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Sales"
    sheet.append(["Month", "Amount"])
    for index in range(rows):
        sheet.append([f"m{index}", index])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_small_workbook_keeps_the_pipe_separated_format():
    text = extract_text_from_xlsx(_workbook(2), "sales.xlsx")
    assert text.startswith("Excel sheet data: ### Sales ###\nMonth|Amount\nm0|0\nm1|1")


def test_large_workbook_is_indexed_as_schema_and_sample(monkeypatch):
    monkeypatch.setattr("eneo.files.tabular_index.TABULAR_INDEX_MAX_CHARS", 200)

    text = extract_text_from_xlsx(_workbook(60), "sales.xlsx")

    assert text.startswith("File: sales.xlsx\n\nLarge table: 60 rows.")
    assert 'Sheet "Sales" (60 rows): Month, Amount\nm0|0\nm1|1' in text
