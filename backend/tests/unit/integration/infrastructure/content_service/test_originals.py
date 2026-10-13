"""Which synced files keep their original bytes, and the tools-only schema stub."""

import io

from openpyxl import Workbook

from eneo.integration.infrastructure.content_service.originals import (
    build_tabular_placeholder_text,
    is_tabular,
    original_media_type,
    retain_original_bytes,
)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _workbook(*sheets: tuple[str, list[str]]) -> bytes:
    book = Workbook()
    book.remove(book.active)
    for name, header in sheets:
        book.create_sheet(name).append(header)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


class TestAllowlist:
    def test_tabular_extensions_are_retained_with_their_media_type(self):
        assert original_media_type("Budget 2026.XLSX") == XLSX
        assert original_media_type("export.csv") == "text/csv"
        assert original_media_type("export.tsv") == "text/tab-separated-values"
        assert retain_original_bytes("a/b/report.xlsx")

    def test_other_documents_keep_text_only(self):
        for name in ("deck.pptx", "policy.docx", "scan.pdf", "notes.txt", "noext"):
            assert original_media_type(name) is None
            assert not retain_original_bytes(name)
            assert not is_tabular(name)

    def test_header_decides_only_without_an_extension(self):
        assert original_media_type("download", "text/csv; charset=utf-8") == "text/csv"
        assert original_media_type("deck.pptx", XLSX) is None
        assert original_media_type("download", "application/pdf") is None


class TestPlaceholder:
    def test_lists_every_sheet_with_its_header_row(self):
        text = build_tabular_placeholder_text(
            "sales.xlsx",
            _workbook(("Sales", ["Month", "Region", "Amount"]), ("Notes", ["Note"])),
        )
        assert text.startswith("Spreadsheet: sales.xlsx")
        assert 'Sheet "Sales": Month, Region, Amount' in text
        assert 'Sheet "Notes": Note' in text
        assert "not indexed for search" in text

    def test_delimited_text_uses_its_first_line(self):
        assert "Columns: id, name" in build_tabular_placeholder_text(
            "people.csv", b"\xef\xbb\xbfid,name\n1,Ada\n"
        )
        assert "Columns: id, name" in build_tabular_placeholder_text(
            "people.tsv", b"id\tname\n1\tAda\n"
        )

    def test_unreadable_bytes_still_yield_a_stub(self):
        text = build_tabular_placeholder_text("broken.xlsx", b"not a workbook")
        assert text.startswith("Spreadsheet: broken.xlsx")
        assert "could not be read" in text

    def test_stub_is_bounded(self):
        headers = [f"column_{index}" for index in range(400)]
        text = build_tabular_placeholder_text("wide.xlsx", _workbook(("Wide", headers)))
        assert len(text) <= 2000
