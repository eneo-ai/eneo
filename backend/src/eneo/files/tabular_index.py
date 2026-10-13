"""How much of a spreadsheet goes into the search index.

Every row is indexed while the serialised table fits the budget, so a file can
be found by any value in it. Beyond the budget only the schema and a sample of
rows per sheet are indexed: enough to find the file by name, column or a
sampled value, while the full table stays available to the table analysis
tools through the retained original. Both the upload and the integration
extractors apply this, so uploaded and synced spreadsheets behave the same.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass

# Roughly the serialised size of a long report; a table that fits is indexed
# whole. Row lines run around 80 characters, so this is a few thousand rows.
TABULAR_INDEX_MAX_CHARS = 200_000
# Rows per sheet kept in the index when the table exceeds the budget.
TABULAR_INDEX_SAMPLE_ROWS = 50


@dataclass(frozen=True)
class IndexedSheet:
    """One sheet as the extractor serialised it: a header and one line per row."""

    name: str | None
    columns: Sequence[str]
    rows: Sequence[str]


def fits_index_budget(text: str) -> bool:
    return len(text) <= TABULAR_INDEX_MAX_CHARS


def delimited_index_text(filename: str, text: str) -> str:
    """A CSV or TSV file as it is while it fits the budget, else schema and sample."""
    if fits_index_budget(text):
        return text
    delimiter = "\t" if filename.lower().endswith(".tsv") else ","
    lines = text.splitlines()
    columns: list[str] = next(csv.reader(lines[:1], delimiter=delimiter), None) or []
    return tabular_sample_text(filename, [IndexedSheet(None, columns, lines[1:])])


def tabular_sample_text(filename: str, sheets: Sequence[IndexedSheet]) -> str:
    """Schema plus a bounded sample of rows for a table over the index budget."""
    total_rows = sum(len(sheet.rows) for sheet in sheets)
    parts = [
        f"File: {filename}",
        f"Large table: {total_rows} rows. A sample of each sheet is indexed "
        "below; the complete file is available to the table analysis tools.",
    ]
    for sheet in sheets:
        label = f'Sheet "{sheet.name}"' if sheet.name else "Table"
        header = ", ".join(str(column) for column in sheet.columns)
        lines = [f"{label} ({len(sheet.rows)} rows): {header}"]
        lines.extend(sheet.rows[:TABULAR_INDEX_SAMPLE_ROWS])
        parts.append("\n".join(lines))
    return "\n\n".join(parts)[:TABULAR_INDEX_MAX_CHARS]
