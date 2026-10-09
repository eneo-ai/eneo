"""Native preview row references are coordinates, never copied data or access grants."""

import json
import re
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from eneo.files.model_file_references import file_handle

_SOURCE = re.compile(
    r'^> \((.{1,200}), file ([0-9a-f-]{36}); sheet ("(?:[^"\\]|\\.)*"), source rows (\[[0-9,]+\])\)$',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TableRowSelection:
    file_id: UUID
    filename: str
    sheet: str
    source_rows: list[int]

    def reference(self) -> dict[str, object]:
        return {
            "url": file_handle(self.file_id),
            "filename": self.filename,
            **({"sheet": self.sheet} if self.sheet else {}),
            "source_rows": self.source_rows,
        }


def parse_table_selection(question: str) -> TableRowSelection | None:
    """Only the opening native quote; file authorization remains the caller's job."""
    for line in question.splitlines():
        if not line.startswith(">"):
            break
        match = _SOURCE.fullmatch(line)
        if not match:
            continue
        try:
            sheet: object = json.loads(match[3])
            rows: object = json.loads(match[4])
            if not isinstance(sheet, str) or not isinstance(rows, list):
                return None
            values = cast(list[Any], rows)
            if not 1 <= len(values) <= 500 or any(
                type(row) is not int or not 2 <= row <= 1_048_576 for row in values
            ):
                return None
            return TableRowSelection(
                UUID(match[2]), match[1], sheet, sorted(set(values))
            )
        except (ValueError, TypeError):
            return None
    return None
