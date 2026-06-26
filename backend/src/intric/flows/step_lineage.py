from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal, Protocol, TypeAlias, TypeGuard

from intric.flows.template_reference_analyzer import TemplateReference


class _StepReferenceFields(Protocol):
    @property
    def step_order(self) -> int: ...

    @property
    def plan_step_ref(self) -> str | None: ...

    @property
    def existing_step_ref(self) -> str | None: ...


_StepReferenceSource: TypeAlias = Mapping[str, object] | _StepReferenceFields
_EXISTING_STEP_REF_PREFIX = "existing_step_"


def existing_step_ref_for_order(step_order: int) -> str:
    if step_order < 1:
        raise ValueError("Existing step refs are 1-based.")
    return f"{_EXISTING_STEP_REF_PREFIX}{step_order}"


def existing_step_order_from_ref(existing_step_ref: str | None) -> int | None:
    if existing_step_ref is None or not existing_step_ref.startswith(
        _EXISTING_STEP_REF_PREFIX
    ):
        return None
    raw_order = existing_step_ref.removeprefix(_EXISTING_STEP_REF_PREFIX)
    if not raw_order.isdigit():
        return None
    step_order = int(raw_order)
    # Reject non-canonical aliases such as existing_step_01.
    if raw_order != str(step_order):
        return None
    return step_order if step_order >= 1 else None


def build_step_ref_mapping(steps: Iterable[_StepReferenceSource]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for step in steps:
        step_order = _step_order(step)
        if not _is_step_order(step_order):
            continue
        for key in ("plan_step_ref", "existing_step_ref"):
            raw_ref = _step_ref(step, key)
            if isinstance(raw_ref, str) and raw_ref.strip():
                mapping[raw_ref.strip()] = step_order
    return mapping


def resolve_upstream_step_orders(
    *,
    input_source: str | None,
    step_order: int,
    references: Iterable[TemplateReference],
    max_prior_step_order: int,
) -> list[int]:
    orders: set[int] = set()
    if input_source == "previous_step" and step_order > 1:
        orders.add(step_order - 1)
    elif input_source == "all_previous_steps" and step_order > 1:
        orders.update(range(1, step_order))
    orders.update(
        resolve_reference_step_orders(
            references=references,
            max_prior_step_order=max_prior_step_order,
        )
    )
    return sorted(orders)


def resolve_reference_step_orders(
    *,
    references: Iterable[TemplateReference],
    max_prior_step_order: int,
) -> list[int]:
    orders: set[int] = set()
    for reference in references:
        referenced_order = reference.step_order
        if (
            isinstance(referenced_order, int)
            and 1 <= referenced_order <= max_prior_step_order
        ):
            orders.add(referenced_order)
    return sorted(orders)


def _step_order(step: _StepReferenceSource) -> object:
    if isinstance(step, Mapping):
        return step.get("step_order")
    return step.step_order


def _is_step_order(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _step_ref(
    step: _StepReferenceSource,
    key: Literal["plan_step_ref", "existing_step_ref"],
) -> object:
    if isinstance(step, Mapping):
        return step.get(key)
    if key == "plan_step_ref":
        return step.plan_step_ref
    return step.existing_step_ref
