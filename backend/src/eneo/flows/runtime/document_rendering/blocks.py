from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.exceptions import TypedIOValidationException

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
# ("List Bullet", "List Bullet 2", "List Bullet 3").
MAX_LIST_LEVEL = 2


class DocumentStructureError(TypedIOValidationException):
    """Document structure is outside the supported rendering profile."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code=FlowApiErrorCode.TYPED_IO_RENDER_FAILED.value)


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
            level = self.item_levels[index]
            if not 0 <= level <= MAX_LIST_LEVEL:
                raise DocumentStructureError(
                    f"Lists support at most {MAX_LIST_LEVEL + 1} levels."
                )
            return level
        return 0


EMPTY_VALUE_PLACEHOLDER = "-"
