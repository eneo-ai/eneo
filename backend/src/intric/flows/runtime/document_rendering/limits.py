"""Resource guardrails for generated PDF/DOCX rendering.

These limits protect worker CPU and memory. They are intentionally separate from
flow execution limits, file upload limits, and LLM token budgets.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.flows.runtime.document_rendering.blocks import DocumentBlock
from intric.main.exceptions import TypedIOValidationException


@dataclass(frozen=True)
class DocumentRenderLimits:
    max_source_chars: int = 500_000
    max_blocks: int = 2_000
    max_text_chars: int = 500_000
    max_table_rows: int = 5_000
    max_table_columns: int = 50
    max_table_cells: int = 50_000
    max_cell_chars: int = 20_000
    max_list_items: int = 5_000
    max_structured_nodes: int = 10_000
    max_structured_depth: int = 32
    max_object_fields: int = 200


DEFAULT_DOCUMENT_RENDER_LIMITS = DocumentRenderLimits()


class DocumentRenderLimitExceeded(TypedIOValidationException):
    """Raised when generated output exceeds document rendering guardrails."""


def ensure_source_within_limits(
    text: str,
    *,
    limits: DocumentRenderLimits = DEFAULT_DOCUMENT_RENDER_LIMITS,
) -> None:
    if len(text) <= limits.max_source_chars:
        return
    _raise_document_too_large("source_chars", len(text), limits.max_source_chars)


def ensure_structured_value_within_limits(
    value: dict[str, Any] | list[Any],
    *,
    limits: DocumentRenderLimits = DEFAULT_DOCUMENT_RENDER_LIMITS,
) -> None:
    stack: list[tuple[Any, int]] = [(value, 1)]
    seen_container_ids: set[int] = set()
    node_count = 0
    total_text_chars = 0
    total_list_items = 0

    while stack:
        current, depth = stack.pop()
        if depth > limits.max_structured_depth:
            _raise_document_too_large(
                "structured_depth",
                depth,
                limits.max_structured_depth,
            )

        if isinstance(current, dict):
            current_dict = cast(dict[str, Any], current)
            _reject_reused_container(current_dict, seen_container_ids)
            node_count += 1
            if node_count > limits.max_structured_nodes:
                _raise_document_too_large(
                    "structured_nodes",
                    node_count,
                    limits.max_structured_nodes,
                )
            if len(current_dict) > limits.max_object_fields:
                _raise_document_too_large(
                    "object_fields",
                    len(current_dict),
                    limits.max_object_fields,
                )
            total_text_chars += sum(len(str(key)) for key in current_dict)
            _check_text_limit(total_text_chars, limits)
            stack.extend((child, depth + 1) for child in current_dict.values())
            continue

        if isinstance(current, list):
            current_list = cast(list[Any], current)
            _reject_reused_container(current_list, seen_container_ids)
            node_count += 1
            if node_count > limits.max_structured_nodes:
                _raise_document_too_large(
                    "structured_nodes",
                    node_count,
                    limits.max_structured_nodes,
                )
            total_list_items += len(current_list)
            if total_list_items > limits.max_list_items:
                _raise_document_too_large(
                    "list_items",
                    total_list_items,
                    limits.max_list_items,
                )
            stack.extend((child, depth + 1) for child in current_list)
            continue

        total_text_chars += len(_scalar_render_text(current))
        _check_text_limit(total_text_chars, limits)


def ensure_blocks_within_limits(
    blocks: Sequence[DocumentBlock],
    *,
    limits: DocumentRenderLimits = DEFAULT_DOCUMENT_RENDER_LIMITS,
) -> None:
    if len(blocks) > limits.max_blocks:
        _raise_document_too_large("blocks", len(blocks), limits.max_blocks)

    total_text_chars = 0
    total_table_rows = 0
    total_table_cells = 0
    total_list_items = 0

    for block in blocks:
        if block.kind == "table":
            total_table_rows += len(block.rows)
            if total_table_rows > limits.max_table_rows:
                _raise_document_too_large(
                    "table_rows",
                    total_table_rows,
                    limits.max_table_rows,
                )
            for row in block.rows:
                if len(row) > limits.max_table_columns:
                    _raise_document_too_large(
                        "table_columns",
                        len(row),
                        limits.max_table_columns,
                    )
                total_table_cells += len(row)
                if total_table_cells > limits.max_table_cells:
                    _raise_document_too_large(
                        "table_cells",
                        total_table_cells,
                        limits.max_table_cells,
                    )
                for cell in row:
                    if len(cell) > limits.max_cell_chars:
                        _raise_document_too_large(
                            "cell_chars",
                            len(cell),
                            limits.max_cell_chars,
                        )
                    total_text_chars += len(cell)
                    _check_text_limit(total_text_chars, limits)
            continue

        if block.items:
            total_list_items += len(block.items)
            if total_list_items > limits.max_list_items:
                _raise_document_too_large(
                    "list_items",
                    total_list_items,
                    limits.max_list_items,
                )
            total_text_chars += sum(len(item) for item in block.items)
        else:
            total_text_chars += len(block.text)

        _check_text_limit(total_text_chars, limits)


def _reject_reused_container(
    value: dict[str, Any] | list[Any],
    seen_container_ids: set[int],
) -> None:
    container_id = id(value)
    if container_id in seen_container_ids:
        raise TypedIOValidationException(
            "Document output contains a cyclic or reused structured value.",
            code=FlowApiErrorCode.TYPED_IO_RENDER_FAILED.value,
            context={"metric": "structured_cycle"},
        )
    seen_container_ids.add(container_id)


def _check_text_limit(text_chars: int, limits: DocumentRenderLimits) -> None:
    if text_chars <= limits.max_text_chars:
        return
    _raise_document_too_large("text_chars", text_chars, limits.max_text_chars)


def _raise_document_too_large(metric: str, actual: int, limit: int) -> None:
    raise DocumentRenderLimitExceeded(
        "Document output is too large to render as a file.",
        code=FlowApiErrorCode.TYPED_IO_RENDER_FAILED.value,
        context={"metric": metric, "actual": actual, "limit": limit},
    )


def _scalar_render_text(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
