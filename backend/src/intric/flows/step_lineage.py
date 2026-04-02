from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def build_step_ref_mapping(steps: Iterable[Any]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for step in steps:
        step_order = _read_step_value(step, "step_order")
        if not isinstance(step_order, int):
            continue
        for key in ("plan_step_ref", "existing_step_ref"):
            raw_ref = _read_step_value(step, key)
            if isinstance(raw_ref, str) and raw_ref.strip():
                mapping[raw_ref.strip()] = step_order
    return mapping


def resolve_upstream_step_orders(
    *,
    input_source: Any,
    step_order: int,
    references: list[Any],
    max_prior_step_order: int,
) -> list[int]:
    orders: list[int] = []
    if input_source == "previous_step" and step_order > 1:
        orders.append(step_order - 1)
    elif input_source == "all_previous_steps" and step_order > 1:
        orders.extend(range(1, step_order))
    for reference in references:
        referenced_order = getattr(reference, "step_order", None)
        if isinstance(referenced_order, int) and 1 <= referenced_order <= max_prior_step_order:
            orders.append(referenced_order)
    return list(dict.fromkeys(sorted(orders)))


def _read_step_value(step: Any, key: str) -> Any:
    if isinstance(step, dict):
        return step.get(key)
    return getattr(step, key, None)
