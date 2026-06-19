from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from intric.flows.step_lineage import (
    build_step_ref_mapping,
    resolve_reference_step_orders,
    resolve_upstream_step_orders,
)
from intric.flows.template_reference_analyzer import (
    TemplateReference,
    TemplateReferenceKind,
)


@dataclass(frozen=True)
class _RuntimeStepRef:
    step_order: int
    plan_step_ref: str | None = None
    existing_step_ref: str | None = None


def _reference(step_order: int | None) -> TemplateReference:
    return TemplateReference(
        expression="",
        head="",
        tail="",
        kind=TemplateReferenceKind.STEP,
        step_order=step_order,
    )


def test_build_step_ref_mapping_reads_runtime_step_objects() -> None:
    mapping = build_step_ref_mapping(
        [
            _RuntimeStepRef(1, plan_step_ref=" source ", existing_step_ref=None),
            _RuntimeStepRef(2, plan_step_ref="", existing_step_ref="canonical"),
        ]
    )

    assert mapping == {"source": 1, "canonical": 2}


def test_build_step_ref_mapping_reads_published_snapshot_mappings() -> None:
    steps: list[Mapping[str, object]] = [
        {
            "step_order": 1,
            "plan_step_ref": "draft_source",
            "existing_step_ref": "existing_source",
        },
        {
            "step_order": True,
            "plan_step_ref": "not_step_one",
            "existing_step_ref": None,
        },
        {
            "step_order": "2",
            "plan_step_ref": "not_step_two",
            "existing_step_ref": None,
        },
    ]

    mapping = build_step_ref_mapping(steps)

    assert mapping == {"draft_source": 1, "existing_source": 1}


def test_resolve_reference_step_orders_keeps_completed_prior_references() -> None:
    orders = resolve_reference_step_orders(
        references=[
            _reference(2),
            _reference(1),
            _reference(2),
            _reference(3),
            _reference(None),
        ],
        max_prior_step_order=2,
    )

    assert orders == [1, 2]


def test_resolve_upstream_step_orders_merges_source_and_explicit_references() -> None:
    orders = resolve_upstream_step_orders(
        input_source="all_previous_steps",
        step_order=4,
        references=[_reference(2), _reference(3)],
        max_prior_step_order=3,
    )

    assert orders == [1, 2, 3]


def test_resolve_upstream_step_orders_deduplicates_previous_step_reference() -> None:
    orders = resolve_upstream_step_orders(
        input_source="previous_step",
        step_order=3,
        references=[_reference(2)],
        max_prior_step_order=2,
    )

    assert orders == [2]


def test_resolve_upstream_step_orders_does_not_reference_step_zero() -> None:
    orders = resolve_upstream_step_orders(
        input_source="previous_step",
        step_order=1,
        references=[],
        max_prior_step_order=0,
    )

    assert orders == []


def test_resolve_upstream_step_orders_keeps_reference_only_dependencies() -> None:
    orders = resolve_upstream_step_orders(
        input_source="flow_input",
        step_order=3,
        references=[_reference(1)],
        max_prior_step_order=2,
    )

    assert orders == [1]
