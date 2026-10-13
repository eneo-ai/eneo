"""A spreadsheet is indexed whole while it fits, otherwise as schema and sample."""

from eneo.files.tabular_index import (
    TABULAR_INDEX_MAX_CHARS,
    TABULAR_INDEX_SAMPLE_ROWS,
    IndexedSheet,
    delimited_index_text,
    fits_index_budget,
    tabular_sample_text,
)


def _sheet(name: str, rows: int, width: int = 3) -> IndexedSheet:
    columns = [f"c{i}" for i in range(width)]
    return IndexedSheet(
        name=name,
        columns=columns,
        rows=[
            " | ".join(f"{column}: {row}-{column}" for column in columns)
            for row in range(rows)
        ],
    )


def test_budget_is_measured_on_the_serialised_text():
    assert fits_index_budget("x" * TABULAR_INDEX_MAX_CHARS)
    assert not fits_index_budget("x" * (TABULAR_INDEX_MAX_CHARS + 1))


def test_sample_keeps_schema_counts_and_the_first_rows_of_every_sheet():
    text = tabular_sample_text("big.xlsx", [_sheet("Sales", 5000), _sheet("Notes", 2)])

    assert text.startswith("File: big.xlsx\n\nLarge table: 5002 rows.")
    assert "table analysis tools" in text
    assert 'Sheet "Sales" (5000 rows): c0, c1, c2' in text
    assert 'Sheet "Notes" (2 rows): c0, c1, c2' in text
    assert f"c0: {TABULAR_INDEX_SAMPLE_ROWS - 1}-c0" in text
    assert f"c0: {TABULAR_INDEX_SAMPLE_ROWS}-c0" not in text
    assert "c0: 1-c0" in text


def test_unnamed_table_is_labelled_without_a_sheet_name():
    table = IndexedSheet(name=None, columns=["id", "name"], rows=["1,Ada", "2,Bo"])
    text = tabular_sample_text("people.csv", [table])
    assert "Table (2 rows): id, name\n1,Ada\n2,Bo" in text


def test_sample_never_exceeds_the_budget():
    wide = IndexedSheet(
        name="Wide",
        columns=[f"column_{i}" for i in range(5000)],
        rows=["x" * 10_000 for _ in range(TABULAR_INDEX_SAMPLE_ROWS)],
    )
    assert len(tabular_sample_text("wide.xlsx", [wide])) <= TABULAR_INDEX_MAX_CHARS


def test_delimited_file_is_indexed_as_is_while_it_fits():
    text = "id,name\n1,Ada\n"
    assert delimited_index_text("people.csv", text) is text


def test_delimited_file_over_budget_keeps_header_and_sample(monkeypatch):
    monkeypatch.setattr("eneo.files.tabular_index.TABULAR_INDEX_MAX_CHARS", 300)
    rows = "\n".join(f"{i}\t{i * 2}" for i in range(100))
    text = delimited_index_text("pairs.tsv", f"n\tdouble\n{rows}\n")
    assert text.startswith("File: pairs.tsv\n\nLarge table: 100 rows.")
    assert "Table (100 rows): n, double" in text
