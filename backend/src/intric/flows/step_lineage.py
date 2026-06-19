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
