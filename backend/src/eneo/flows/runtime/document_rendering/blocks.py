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

# Heading depth the renderers accept. Word ships Heading 1-9 but accessibility
# guidance and the HTML writer stop at six; deeper markdown is rejected, not
# silently flattened.
MAX_HEADING_LEVEL = 6
# Nested list depth the writers can express with the built-in list styles
# ("List Bullet", "List Bullet 2", "List Bullet 3"); deeper items are clamped.
MAX_LIST_LEVEL = 2


@dataclass(frozen=True)
class InlineTextRun:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    strikethrough: bool = False
    href: str | None = None


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
    # Nesting depth per list item (0 = top level), parallel to ``items``.
    item_levels: tuple[int, ...] = ()
    # First number of a numbered list.
    start: int = 1

    def item_level(self, index: int) -> int:
        if index < len(self.item_levels):
            return min(max(self.item_levels[index], 0), MAX_LIST_LEVEL)
        return 0


EMPTY_VALUE_PLACEHOLDER = "-"
