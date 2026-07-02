from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DocumentBlockKind = Literal[
    "empty",
    "heading",
    "paragraph",
    "bullet_list",
    "numbered_list",
    "code",
    "table",
]


@dataclass(frozen=True)
class InlineTextRun:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    strikethrough: bool = False


InlineRuns = tuple[InlineTextRun, ...]


@dataclass(frozen=True)
class DocumentBlock:
    kind: DocumentBlockKind
    text: str = ""
    level: int = 0
    items: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()
    runs: InlineRuns = ()
    item_runs: tuple[InlineRuns, ...] = ()
    row_runs: tuple[tuple[InlineRuns, ...], ...] = ()


EMPTY_VALUE_PLACEHOLDER = "-"
