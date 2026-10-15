"""Synced spreadsheets: the extracted text is complete; the index form is decided later."""

import io

from openpyxl import Workbook

from eneo.integration.infrastructure.content_service.utils import (
    extract_text_from_xlsx,
    sync_index_text,
    xlsx_index_text,
)

BUDGET = "eneo.files.tabular_index.TABULAR_INDEX_MAX_CHARS"


def _workbook(rows: int, sheets: int = 1) -> bytes:
    book = Workbook()
    for index in range(sheets):
        sheet = book.active if index == 0 else book.create_sheet()
        sheet.title = "Sales" if index == 0 else f"Extra{index}"
        sheet.append(["Month", "Amount"])
        for row in range(rows):
            sheet.append([f"m{row}", row])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_small_workbook_keeps_the_pipe_separated_format():
    text = extract_text_from_xlsx(_workbook(2), "sales.xlsx")
    assert text.startswith("Excel sheet data: ### Sales ###\nMonth|Amount\nm0|0\nm1|1")


def test_extraction_returns_every_row_whatever_the_budget(monkeypatch):
    monkeypatch.setattr(BUDGET, 200)
    text = extract_text_from_xlsx(_workbook(60), "sales.xlsx")
    assert text.startswith("Excel sheet data: ### Sales ###\nMonth|Amount\nm0|0")
    assert "m59|59" in text


def test_index_text_is_schema_and_sample_over_the_budget(monkeypatch):
    monkeypatch.setattr(BUDGET, 200)
    text = extract_text_from_xlsx(_workbook(60), "sales.xlsx")

    sample = xlsx_index_text("sales.xlsx", text)

    assert sample is not None
    assert sample.startswith("File: sales.xlsx\n\nLarge table: 60 rows.")
    assert 'Sheet "Sales" (60 rows): Month, Amount\nm0|0\nm1|1' in sample


def test_index_text_covers_every_sheet(monkeypatch):
    # Over the budget as a whole, with room for a 50-row sample of each sheet.
    monkeypatch.setattr(BUDGET, 1_500)
    text = extract_text_from_xlsx(_workbook(200, sheets=2), "sales.xlsx")

    sample = xlsx_index_text("sales.xlsx", text)

    assert sample is not None
    assert "Large table: 400 rows." in sample
    assert 'Sheet "Sales" (200 rows): Month, Amount\nm0|0' in sample
    assert 'Sheet "Extra1" (200 rows): Month, Amount\nm0|0' in sample
    assert "m49|49" in sample and "m50|50" not in sample


def test_no_index_text_while_the_workbook_fits():
    text = extract_text_from_xlsx(_workbook(2), "sales.xlsx")
    assert xlsx_index_text("sales.xlsx", text) is None


def test_no_index_text_for_text_in_another_layout(monkeypatch):
    monkeypatch.setattr(BUDGET, 10)
    assert xlsx_index_text("sales.xlsx", "plain prose, not a workbook dump") is None


def test_sync_index_text_needs_a_retained_original(monkeypatch):
    monkeypatch.setattr(BUDGET, 200)
    text = extract_text_from_xlsx(_workbook(60), "sales.xlsx")

    assert sync_index_text("sales.xlsx", text, retained=False) is None
    sample = sync_index_text("sales.xlsx", text, retained=True)
    assert sample is not None and sample.startswith("File: sales.xlsx")


def test_sync_index_text_is_none_for_small_tables_and_other_files(monkeypatch):
    assert (
        sync_index_text("sales.xlsx", "Excel sheet data: ### S ###\na|b", retained=True)
        is None
    )
    monkeypatch.setattr(BUDGET, 10)
    assert sync_index_text("deck.pptx", "x" * 50, retained=True) is None


def test_sync_index_text_samples_delimited_files(monkeypatch):
    monkeypatch.setattr(BUDGET, 300)
    rows = "\n".join(f"{i}\t{i * 2}" for i in range(100))

    sample = sync_index_text("pairs.tsv", f"n\tdouble\n{rows}\n", retained=True)

    assert sample is not None
    assert sample.startswith("File: pairs.tsv\n\nLarge table: 100 rows.")
    assert "Table (100 rows): n, double" in sample
