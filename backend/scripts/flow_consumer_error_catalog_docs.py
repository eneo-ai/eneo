from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from eneo.flows.flow_error_taxonomy import (
    FLOW_ERROR_CATEGORY_ORDER,
    FLOW_ERROR_TAXONOMY,
    validate_flow_error_taxonomy,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FLOW_CONSUMER_ERROR_REFERENCE_OUTPUT_PATH = (
    REPO_ROOT
    / "frontend"
    / "apps"
    / "docs-site"
    / "src"
    / "content"
    / "guides"
    / "flows"
    / "reference"
    / "errors.mdx"
)


@dataclass(frozen=True, slots=True)
class FlowConsumerErrorCatalogRow:
    category: str
    code: str
    handling_phase: str
    consumer_action: str


def flow_consumer_error_catalog_rows() -> tuple[FlowConsumerErrorCatalogRow, ...]:
    validate_flow_error_taxonomy()
    category_order = {
        category: index for index, category in enumerate(FLOW_ERROR_CATEGORY_ORDER)
    }
    ordered_entries = sorted(
        FLOW_ERROR_TAXONOMY.items(),
        key=lambda item: (category_order[item[1].category], item[0].value),
    )
    return tuple(
        FlowConsumerErrorCatalogRow(
            category=entry.category,
            code=code.value,
            handling_phase=entry.handling_phase,
            consumer_action=entry.consumer_action,
        )
        for code, entry in ordered_entries
    )


def render_flow_consumer_error_catalog_table() -> str:
    rows = tuple(
        (
            row.category,
            f"`{row.code}`",
            row.handling_phase,
            row.consumer_action,
        )
        for row in flow_consumer_error_catalog_rows()
    )
    return _render_markdown_table(
        ("Category", "Code", "Handling phase", "Consumer action"),
        rows,
    )


def render_flow_consumer_error_reference_page() -> str:
    return "\n".join(
        (
            "# Flow error reference",
            "",
            "This page is for teams turning Eneo Flows error codes into clear recovery paths, and it shows which failures belong to request handling and which belong to run execution.",
            "",
            "Use this as the canonical consumer reference for `FlowApiErrorCode`. Task guides link here instead of repeating code lists.",
            "",
            "## How to handle codes",
            "",
            "- Handle `Request path` codes from the failed API response before you create, edit, resume, or rerun a run.",
            "- Handle `Run execution` codes from `run.error.code` while polling or rendering a terminal failed run.",
            "- Handle `Request path or run execution` codes in both places; the same logical failure can surface synchronously or after worker execution.",
            "- Unknown codes should degrade gracefully: show a generic Flow failure message, keep the raw code for support, and avoid automatic destructive retries.",
            "",
            "## Catalog",
            "",
            render_flow_consumer_error_catalog_table(),
            "",
            "Next: [Flows API Guide](/guides/flows-api-guide)",
            "",
        )
    )


def write_flow_consumer_error_reference_page() -> None:
    FLOW_CONSUMER_ERROR_REFERENCE_OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    FLOW_CONSUMER_ERROR_REFERENCE_OUTPUT_PATH.write_text(
        render_flow_consumer_error_reference_page(),
        encoding="utf-8",
    )


def _render_markdown_table(
    headers: tuple[str, ...],
    rows: Sequence[tuple[str, ...]],
) -> str:
    escaped_rows = [tuple(_escape_cell(cell) for cell in row) for row in rows]
    widths = [
        max(len(row[column_index]) for row in (headers, *escaped_rows))
        for column_index in range(len(headers))
    ]

    def render_row(cells: tuple[str, ...]) -> str:
        padded_cells = [
            cell.ljust(widths[column_index]) for column_index, cell in enumerate(cells)
        ]
        return f"| {' | '.join(padded_cells)} |"

    separator = tuple("-" * max(3, width) for width in widths)
    return "\n".join(
        [render_row(headers), render_row(separator), *map(render_row, escaped_rows)]
    )


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|")
