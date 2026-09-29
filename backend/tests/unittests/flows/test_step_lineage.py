from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pytest

from eneo.flows.enums import FlowInputSource
from eneo.flows.step_lineage import (
    build_step_ref_mapping,
    existing_step_order_from_ref,
    existing_step_ref_for_order,
    resolve_reference_step_orders,
    resolve_step_upstream_orders,
    resolve_upstream_step_orders,
)
from eneo.flows.template_reference_analyzer import (
    TemplateReference,
    TemplateReferenceKind,
)


@dataclass(frozen=True)
class _RuntimeStepRef:
    step_order: int
    plan_step_ref: str | None = None
    existing_step_ref: str | None = None
    user_description: str | None = None


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
            _RuntimeStepRef(
                1,
                plan_step_ref=" source ",
                existing_step_ref=None,
                user_description=" Source label ",
            ),
            _RuntimeStepRef(2, plan_step_ref="", existing_step_ref="canonical"),
        ]
    )

    assert mapping == {"source": 1, "canonical": 2, "Source label": 1}


def test_build_step_ref_mapping_keeps_plan_ref_over_other_step_label() -> None:
    mapping = build_step_ref_mapping(
        [
            _RuntimeStepRef(
                1,
                plan_step_ref="authored_ref",
                user_description="Authored owner",
            ),
            _RuntimeStepRef(2, user_description=" authored_ref "),
        ]
    )

    assert mapping == {"authored_ref": 1, "Authored owner": 1}


def test_build_step_ref_mapping_duplicate_label_uses_lowest_step_order() -> None:
    mapping = build_step_ref_mapping(
        [
            {"step_order": 2, "user_description": "Duplicate"},
            {"step_order": 1, "user_description": "Duplicate"},
        ]
    )

    assert mapping == {"Duplicate": 1}


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


def test_existing_step_ref_for_order_pins_wire_format() -> None:
    assert existing_step_ref_for_order(3) == "existing_step_3"


def test_existing_step_ref_round_trips_order() -> None:
    ref = existing_step_ref_for_order(12)

    assert existing_step_order_from_ref(ref) == 12


def test_existing_step_ref_rejects_invalid_order() -> None:
    with pytest.raises(ValueError, match="Existing step refs are 1-based."):
        existing_step_ref_for_order(0)


def test_existing_step_order_from_ref_rejects_non_canonical_refs() -> None:
    assert existing_step_order_from_ref(None) is None
    assert existing_step_order_from_ref("existing_step_0") is None
    assert existing_step_order_from_ref("existing_step_01") is None
    assert existing_step_order_from_ref("step_1") is None


def test_resolve_reference_step_orders_keeps_completed_prior_references() -> None:
    orders = resolve_reference_step_orders(
        references=[
            _reference(2),
            _reference(1),
            _reference(2),
            _reference(3),
            _reference(None),
        ],
        step_order=3,
        max_prior_step_order=2,
    )

    assert orders == [1, 2]


def test_resolve_upstream_step_orders_lets_underlag_decide_alone() -> None:
    orders = resolve_upstream_step_orders(
        input_source="all_previous_steps",
        step_order=4,
        binding_references=[_reference(2), _reference(3)],
        max_prior_step_order=3,
    )

    assert orders == [2, 3]


def test_resolve_upstream_step_orders_underlag_without_step_references_reads_no_step() -> (
    None
):
    orders = resolve_upstream_step_orders(
        input_source="previous_step",
        step_order=3,
        binding_references=[],
        max_prior_step_order=2,
    )

    assert orders == []


def test_resolve_upstream_step_orders_uses_input_source_without_underlag() -> None:
    assert resolve_upstream_step_orders(
        input_source="previous_step",
        step_order=3,
        binding_references=None,
        max_prior_step_order=2,
    ) == [2]
    assert resolve_upstream_step_orders(
        input_source="all_previous_steps",
        step_order=4,
        binding_references=None,
        max_prior_step_order=3,
    ) == [1, 2, 3]


def test_resolve_upstream_step_orders_does_not_reference_step_zero() -> None:
    orders = resolve_upstream_step_orders(
        input_source="previous_step",
        step_order=1,
        binding_references=None,
        max_prior_step_order=0,
    )

    assert orders == []


def test_resolve_upstream_step_orders_keeps_reference_only_dependencies() -> None:
    orders = resolve_upstream_step_orders(
        input_source="flow_input",
        step_order=3,
        binding_references=[_reference(1)],
        max_prior_step_order=2,
    )

    assert orders == [1]


def test_resolve_step_upstream_orders_adds_prompt_references_to_underlag() -> None:
    orders = resolve_step_upstream_orders(
        input_source="all_previous_steps",
        step_order=4,
        input_bindings={"question": "Samtal: {{ step_2.output.text }}"},
        prompt_template="Bakgrund: {{ step_1.output.text }}",
        step_ref_mapping={},
        max_prior_step_order=3,
    )

    assert orders == [1, 2]


def test_resolve_step_upstream_orders_prompt_only_reads_the_referenced_step() -> None:
    orders = resolve_step_upstream_orders(
        input_source="previous_step",
        step_order=3,
        input_bindings={"question": "Sammanfatta."},
        prompt_template="Bakgrund: {{ step_1.output.text }}",
        step_ref_mapping={},
        max_prior_step_order=2,
    )

    assert orders == [1]


@pytest.mark.parametrize(
    ("question", "prompt"),
    [
        pytest.param("Samtal: {{ föregående_steg }}", None, id="question"),
        pytest.param("Sammanfatta.", "Bakgrund: {{ föregående_steg }}", id="prompt"),
    ],
)
def test_resolve_step_upstream_orders_reads_previous_step_through_shorthand(
    question: str, prompt: str | None
) -> None:
    orders = resolve_step_upstream_orders(
        input_source="flow_input",
        step_order=3,
        input_bindings={"question": question},
        prompt_template=prompt,
        step_ref_mapping={},
        max_prior_step_order=2,
    )

    assert orders == [2]


def test_resolve_step_upstream_orders_shorthand_on_first_step_reads_no_step() -> None:
    orders = resolve_step_upstream_orders(
        input_source="flow_input",
        step_order=1,
        input_bindings={"question": "{{ föregående_steg }}"},
        prompt_template="{{ föregående_steg }}",
        step_ref_mapping={},
        max_prior_step_order=0,
    )

    assert orders == []


_INPUT_SOURCE_READS = [
    pytest.param(FlowInputSource.FLOW_INPUT, [], id="flow_input"),
    pytest.param(FlowInputSource.HTTP_GET, [], id="http_get"),
    pytest.param(FlowInputSource.PREVIOUS_STEP, [2], id="previous_step"),
    pytest.param(FlowInputSource.ALL_PREVIOUS_STEPS, [1, 2], id="all_previous_steps"),
]


@pytest.mark.parametrize(("source", "expected"), _INPUT_SOURCE_READS)
def test_resolve_upstream_step_orders_reads_what_each_input_source_reads(
    source: FlowInputSource, expected: list[int]
) -> None:
    # The typed member and the value it is stored as name the same source.
    for spelling in (source, source.value):
        assert (
            resolve_upstream_step_orders(
                input_source=spelling,
                step_order=3,
                binding_references=None,
                max_prior_step_order=2,
            )
            == expected
        )


@pytest.mark.parametrize(
    "source", [FlowInputSource.PREVIOUS_STEP, FlowInputSource.ALL_PREVIOUS_STEPS]
)
def test_resolve_upstream_step_orders_first_step_reads_no_prior_step(
    source: FlowInputSource,
) -> None:
    assert (
        resolve_upstream_step_orders(
            input_source=source,
            step_order=1,
            binding_references=None,
            max_prior_step_order=0,
        )
        == []
    )


@pytest.mark.parametrize(
    "unknown",
    [
        # What str() makes of a member: it names no source, so it must not
        # read as "no prior step".
        pytest.param(str(FlowInputSource.PREVIOUS_STEP), id="member-text-form"),
        pytest.param("sideways", id="unknown-value"),
        pytest.param("", id="empty"),
        pytest.param(None, id="absent"),
    ],
)
@pytest.mark.parametrize("binding_references", [None, []])
def test_resolve_upstream_step_orders_fails_closed_on_an_unknown_input_source(
    unknown: object, binding_references: list[TemplateReference] | None
) -> None:
    with pytest.raises(ValueError):
        resolve_upstream_step_orders(
            input_source=unknown,  # pyright: ignore[reportArgumentType]
            step_order=3,
            binding_references=binding_references,
            max_prior_step_order=2,
        )


def test_resolve_step_upstream_orders_fails_closed_on_an_unknown_input_source() -> None:
    with pytest.raises(ValueError):
        resolve_step_upstream_orders(
            input_source=str(FlowInputSource.PREVIOUS_STEP),
            step_order=3,
            input_bindings=None,
            prompt_template=None,
            step_ref_mapping={},
            max_prior_step_order=2,
        )


def test_resolve_step_upstream_orders_reads_the_typed_default_input_source() -> None:
    orders = resolve_step_upstream_orders(
        input_source=FlowInputSource.PREVIOUS_STEP,
        step_order=3,
        input_bindings=None,
        prompt_template="Bakgrund: {{ step_1.output.text }}",
        step_ref_mapping={},
        max_prior_step_order=2,
    )

    assert orders == [1, 2]
