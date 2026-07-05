from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from eneo.flows.enums import RerunDependencyKind
from eneo.flows.flow_run_rerun_graph import (
    RerunGraphStepNotFound,
    build_rerun_invalidation_graph,
)
from eneo.flows.runtime.models import RuntimeStep


def _uuid(value: int) -> UUID:
    return UUID(int=value)


def _step(
    order: int,
    *,
    input_source: str = "flow_input",
    input_bindings: dict[str, Any] | None = None,
    input_config: dict[str, Any] | None = None,
    output_config: dict[str, Any] | None = None,
    output_mode: str = "pass_through",
    user_description: str | None = None,
    plan_step_ref: str | None = None,
    existing_step_ref: str | None = None,
    assistant_snapshot: dict[str, Any] | None = None,
) -> RuntimeStep:
    return RuntimeStep(
        step_id=_uuid(order),
        step_order=order,
        assistant_id=_uuid(1000 + order),
        user_description=user_description,
        input_source=input_source,
        input_bindings=input_bindings,
        input_config=input_config,
        output_mode=output_mode,
        output_config=output_config,
        plan_step_ref=plan_step_ref,
        existing_step_ref=existing_step_ref,
        assistant_snapshot=assistant_snapshot,
    )


def test_previous_step_chain_invalidates_transitive_downstream_steps():
    graph = build_rerun_invalidation_graph(
        steps=[
            _step(1),
            _step(2, input_source="previous_step"),
            _step(3, input_source="previous_step"),
            _step(4),
        ],
        root_step_id=_uuid(1),
    )

    assert graph.invalidated_step_ids == (_uuid(1), _uuid(2), _uuid(3))
    assert graph.invalidated_steps[1].dependency_kinds == (
        RerunDependencyKind.INPUT_SOURCE_PREVIOUS_STEP,
    )
    assert graph.invalidated_steps[2].dependency_kinds == (
        RerunDependencyKind.INPUT_SOURCE_PREVIOUS_STEP,
    )


def test_all_previous_steps_invalidates_consumers_without_unrelated_steps():
    graph = build_rerun_invalidation_graph(
        steps=[
            _step(1),
            _step(2),
            _step(3, input_source="all_previous_steps"),
            _step(4),
        ],
        root_step_id=_uuid(2),
    )

    assert graph.invalidated_step_ids == (_uuid(2), _uuid(3))
    assert graph.invalidated_steps[1].dependency_kinds == (
        RerunDependencyKind.INPUT_SOURCE_ALL_PREVIOUS_STEPS,
    )


@pytest.mark.parametrize(
    ("step_kwargs", "dependency_kind"),
    [
        (
            {"input_bindings": {"question": "{{ step_1.output.text }}"}},
            RerunDependencyKind.INPUT_BINDINGS_QUESTION,
        ),
        (
            {
                "input_bindings": {
                    "source_refs": [{"step_ref": "step_1", "output": "text"}]
                }
            },
            RerunDependencyKind.INPUT_BINDINGS_QUESTION,
        ),
        (
            {
                "input_config": {
                    "url": "https://example.test/{{ step_1.output.id }}",
                    "auth": {"mode": "none"},
                }
            },
            RerunDependencyKind.INPUT_CONFIG_URL,
        ),
        (
            {
                "input_config": {
                    "url": "https://example.test/static",
                    "auth": {"mode": "none"},
                    "custom_headers": [
                        {
                            "name": "X-Case",
                            "value": "{{ step_1.output.id }}",
                            "secret": False,
                        }
                    ],
                }
            },
            RerunDependencyKind.INPUT_CONFIG_HEADERS,
        ),
        (
            {
                "input_config": {
                    "url": "https://example.test/static",
                    "auth": {"mode": "none"},
                    "body": {
                        "mode": "text_template",
                        "template": "{{ step_1.output.text }}",
                    },
                }
            },
            RerunDependencyKind.INPUT_CONFIG_BODY_TEMPLATE,
        ),
        (
            {
                "output_config": {
                    "url": "https://example.test/{{ step_1.output.id }}",
                    "auth": {"mode": "none"},
                }
            },
            RerunDependencyKind.OUTPUT_CONFIG_URL,
        ),
        (
            {
                "output_config": {
                    "url": "https://example.test/static",
                    "auth": {"mode": "none"},
                    "custom_headers": [
                        {
                            "name": "X-Case",
                            "value": "{{ step_1.output.id }}",
                            "secret": False,
                        }
                    ],
                }
            },
            RerunDependencyKind.OUTPUT_CONFIG_HEADERS,
        ),
        (
            {
                "output_config": {
                    "url": "https://example.test/static",
                    "auth": {"mode": "none"},
                    "body": {
                        "mode": "text_template",
                        "template": "{{ step_1.output.text }}",
                    },
                }
            },
            RerunDependencyKind.OUTPUT_CONFIG_BODY_TEMPLATE,
        ),
        (
            {
                "output_mode": "template_fill",
                "output_config": {"bindings": {"case": "{{ step_1.output.id }}"}},
            },
            RerunDependencyKind.OUTPUT_CONFIG_BINDINGS,
        ),
        (
            {"assistant_snapshot": {"instructions": "Use {{ step_1.output.text }}"}},
            RerunDependencyKind.ASSISTANT_SNAPSHOT_INSTRUCTIONS,
        ),
        (
            {"assistant_snapshot": {"instructions": "Use {{föregående_steg}}"}},
            RerunDependencyKind.RUNTIME_ALIAS_PREVIOUS_STEP,
        ),
    ],
)
def test_runtime_interpolated_fields_create_rerun_dependencies(
    step_kwargs: dict[str, Any],
    dependency_kind: RerunDependencyKind,
):
    graph = build_rerun_invalidation_graph(
        steps=[
            _step(1),
            _step(2, **step_kwargs),
            _step(3),
        ],
        root_step_id=_uuid(1),
    )

    assert graph.invalidated_step_ids == (_uuid(1), _uuid(2))
    assert graph.invalidated_steps[1].dependency_kinds == (dependency_kind,)


@pytest.mark.parametrize(
    ("step_kwargs", "dependency_kinds"),
    [
        (
            {
                "input_config": {
                    "url": "https://api.example.test/{{ step_1.output.id }}",
                    "auth": {
                        "mode": "bearer_token",
                        "token": "{{ step_1.output.token }}",
                    },
                    "body": {
                        "mode": "json_template",
                        "template": '{"id": "{{ step_1.output.id }}"}',
                    },
                    "custom_headers": [
                        {
                            "name": "X-Trace",
                            "value": "{{ step_1.output.trace_id }}",
                            "secret": False,
                        }
                    ],
                }
            },
            (
                RerunDependencyKind.INPUT_CONFIG_BODY_TEMPLATE,
                RerunDependencyKind.INPUT_CONFIG_HEADERS,
                RerunDependencyKind.INPUT_CONFIG_URL,
            ),
        ),
        (
            {
                "output_config": {
                    "url": "https://hook.example.test/{{ step_1.output.id }}",
                    "auth": {
                        "mode": "api_key",
                        "header_name": "X-{{ step_1.output.header }}",
                        "key": "{{ step_1.output.token }}",
                    },
                    "body": {
                        "mode": "text_template",
                        "template": "{{ step_1.output.text }}",
                    },
                    "custom_headers": [],
                }
            },
            (
                RerunDependencyKind.OUTPUT_CONFIG_BODY_TEMPLATE,
                RerunDependencyKind.OUTPUT_CONFIG_HEADERS,
                RerunDependencyKind.OUTPUT_CONFIG_URL,
            ),
        ),
    ],
)
def test_authored_http_config_templates_create_rerun_dependencies(
    step_kwargs,
    dependency_kinds,
):
    graph = build_rerun_invalidation_graph(
        steps=[
            _step(1),
            _step(2, **step_kwargs),
        ],
        root_step_id=_uuid(1),
    )

    assert graph.invalidated_step_ids == (_uuid(1), _uuid(2))
    assert graph.invalidated_steps[1].dependency_kinds == dependency_kinds


def test_authored_http_body_none_does_not_create_body_dependency():
    graph = build_rerun_invalidation_graph(
        steps=[
            _step(1),
            _step(
                2,
                output_config={
                    "url": "https://hook.example.test/static",
                    "auth": {"mode": "none"},
                    "body": {
                        "mode": "none",
                        "template": "{{ step_1.output.text }}",
                    },
                    "custom_headers": [],
                },
            ),
        ],
        root_step_id=_uuid(1),
    )

    assert graph.invalidated_step_ids == (_uuid(1),)


def test_step_refs_and_user_labels_create_rerun_dependencies():
    graph = build_rerun_invalidation_graph(
        steps=[
            _step(
                1,
                user_description="Human label",
                plan_step_ref="source_record",
                existing_step_ref="canonical_source",
            ),
            _step(
                2,
                input_bindings={
                    "question": (
                        "{{ source_record.output.id }} "
                        "{{ canonical_source.output.text }} "
                        "{{ Human label.output.text }}"
                    )
                },
            ),
        ],
        root_step_id=_uuid(1),
    )

    assert graph.invalidated_step_ids == (_uuid(1), _uuid(2))
    assert graph.invalidated_steps[1].dependency_kinds == (
        RerunDependencyKind.INPUT_BINDINGS_QUESTION,
    )


def test_future_step_template_references_do_not_invalidate_backwards():
    graph = build_rerun_invalidation_graph(
        steps=[
            _step(1),
            _step(2, input_bindings={"question": "{{ step_3.output.text }}"}),
            _step(3),
        ],
        root_step_id=_uuid(3),
    )

    assert graph.invalidated_step_ids == (_uuid(3),)


def test_missing_root_step_is_explicit():
    with pytest.raises(RerunGraphStepNotFound):
        build_rerun_invalidation_graph(steps=[_step(1)], root_step_id=_uuid(99))
