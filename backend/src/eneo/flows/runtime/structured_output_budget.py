from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.exceptions import TypedIOValidationException


def structured_output_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _ensure_size_allowed(
    *, measured_bytes: int, ceiling_bytes: int, items_completed: int, items_total: int
) -> None:
    if measured_bytes > ceiling_bytes:
        raise TypedIOValidationException(
            "Structured step output exceeds the inline output ceiling.",
            code=FlowApiErrorCode.TYPED_IO_STRUCTURED_OUTPUT_EXCEEDS_LIMIT.value,
            context={
                "items_completed": items_completed,
                "items_total": items_total,
                "measured_bytes": measured_bytes,
                "ceiling_bytes": ceiling_bytes,
            },
        )


def ensure_structured_output_allowed(
    value: object,
    *,
    ceiling_bytes: int,
    items_completed: int = 1,
    items_total: int = 1,
) -> None:
    if value is not None:
        _ensure_size_allowed(
            measured_bytes=len(structured_output_json(value).encode("utf-8")),
            ceiling_bytes=ceiling_bytes,
            items_completed=items_completed,
            items_total=items_total,
        )


class StructuredOutputBudget:
    """Count enriched items using the final JSON encoding, including framing."""

    def __init__(self, *, array_key: str, ceiling_bytes: int, items_total: int) -> None:
        self._measured_bytes = len(
            structured_output_json({array_key: []}).encode("utf-8")
        )
        self._item_count = 0
        self._ceiling_bytes = ceiling_bytes
        self._items_total = items_total

    def admit(self, items: Sequence[dict[str, Any]], *, items_completed: int) -> None:
        for item in items:
            self._measured_bytes += len(structured_output_json(item).encode("utf-8"))
            if self._item_count:
                self._measured_bytes += len(", ")
            self._item_count += 1
        _ensure_size_allowed(
            measured_bytes=self._measured_bytes,
            ceiling_bytes=self._ceiling_bytes,
            items_completed=items_completed,
            items_total=self._items_total,
        )

    def set_failure_progress(self, exc: BaseException, *, items_completed: int) -> None:
        if (
            isinstance(exc, TypedIOValidationException)
            and exc.code
            == FlowApiErrorCode.TYPED_IO_STRUCTURED_OUTPUT_EXCEEDS_LIMIT.value
        ):
            exc.context = {
                **(exc.context or {}),
                "items_completed": min(items_completed, self._items_total),
                "items_total": self._items_total,
            }
