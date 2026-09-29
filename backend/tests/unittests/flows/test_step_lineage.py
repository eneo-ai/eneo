from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pytest

from eneo.flows.enums import FlowInputSource, FlowOutputMode
from eneo.flows.step_lineage import (
    build_step_ref_mapping,
    existing_step_order_from_ref,
    existing_step_ref_for_order,
    resolve_reference_step_orders,
    resolve_step_input_orders,
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


def test_resolve_step_input_orders_adds_prompt_references_to_underlag() -> None:
    orders = resolve_step_input_orders(
        input_source="all_previous_steps",
        step_order=4,
        input_bindings={"question": "Samtal: {{ step_2.output.text }}"},
        prompt_template="Bakgrund: {{ step_1.output.text }}",
        step_ref_mapping={},
        max_prior_step_order=3,
    )

    assert orders == [1, 2]


def test_resolve_step_input_orders_prompt_only_reads_the_referenced_step() -> None:
    orders = resolve_step_input_orders(
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
def test_resolve_step_input_orders_reads_previous_step_through_shorthand(
    question: str, prompt: str | None
) -> None:
    orders = resolve_step_input_orders(
        input_source="flow_input",
        step_order=3,
        input_bindings={"question": question},
        prompt_template=prompt,
        step_ref_mapping={},
        max_prior_step_order=2,
    )

    assert orders == [2]


def test_resolve_step_input_orders_shorthand_on_first_step_reads_no_step() -> None:
    orders = resolve_step_input_orders(
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


def test_resolve_step_input_orders_fails_closed_on_an_unknown_input_source() -> None:
    with pytest.raises(ValueError):
        resolve_step_input_orders(
            input_source=str(FlowInputSource.PREVIOUS_STEP),
            step_order=3,
            input_bindings=None,
            prompt_template=None,
            step_ref_mapping={},
            max_prior_step_order=2,
        )


def test_resolve_step_input_orders_reads_the_typed_default_input_source() -> None:
    orders = resolve_step_input_orders(
        input_source=FlowInputSource.PREVIOUS_STEP,
        step_order=3,
        input_bindings=None,
        prompt_template="Bakgrund: {{ step_1.output.text }}",
        step_ref_mapping={},
        max_prior_step_order=2,
    )

    assert orders == [1, 2]


def _upstream(
    *,
    step_order: int = 3,
    input_source: FlowInputSource | str = FlowInputSource.FLOW_INPUT,
    input_bindings: dict[str, object] | None = None,
    prompt_template: str | None = None,
    output_mode: FlowOutputMode | str = FlowOutputMode.PASS_THROUGH,
    input_config: dict[str, object] | None = None,
    output_config: dict[str, object] | None = None,
    step_ref_mapping: dict[str, int] | None = None,
) -> list[int]:
    return resolve_step_upstream_orders(
        input_source=input_source,
        step_order=step_order,
        input_bindings=input_bindings,
        prompt_template=prompt_template,
        output_mode=output_mode,
        input_config=input_config,
        output_config=output_config,
        step_ref_mapping=step_ref_mapping or {},
        max_prior_step_order=step_order - 1,
    )


def _http_config(**fields: object) -> dict[str, object]:
    return {"url": "https://example.org/hook", "auth": {"mode": "none"}, **fields}


_STEP_1 = "{{ step_1.output.text }}"

# Every string of an authored HTTP config the request compiler interpolates,
# each carrying a read of step 1 (the compiler's own list is pinned in
# http_transport/test_compiler.py).
_HTTP_TEMPLATE_CARRIERS = [
    pytest.param(_http_config(url=f"https://example.org/{_STEP_1}"), id="url"),
    pytest.param(
        _http_config(
            url=f"https://example.org/{_STEP_1}",
            retrieval_policy={"version": 1, "mode": "best_effort"},
        ),
        id="url-with-a-key-the-lineage-does-not-read",
    ),
    pytest.param(
        _http_config(
            body={"mode": "json_template", "template": f'{{"t": "{_STEP_1}"}}'}
        ),
        id="json-body",
    ),
    pytest.param(
        _http_config(body={"mode": "text_template", "template": _STEP_1}),
        id="text-body",
    ),
    pytest.param(
        _http_config(custom_headers=[{"name": "X-Text", "value": _STEP_1}]),
        id="header-value",
    ),
    pytest.param(
        _http_config(auth={"mode": "api_key", "header_name": _STEP_1, "key": "k"}),
        id="api-key-header-name",
    ),
    pytest.param(
        _http_config(auth={"mode": "basic_auth", "username": _STEP_1, "password": "p"}),
        id="basic-username",
    ),
]

# A credential is a literal (validation refuses a template in one, the
# compiler never interpolates one), so it names no read.
_CREDENTIAL_FIELDS = [
    pytest.param(
        _http_config(auth={"mode": "bearer_token", "token": _STEP_1}), id="bearer"
    ),
    pytest.param(
        _http_config(auth={"mode": "api_key", "header_name": "X-Key", "key": _STEP_1}),
        id="api-key",
    ),
    pytest.param(
        _http_config(auth={"mode": "basic_auth", "username": "u", "password": _STEP_1}),
        id="basic-password",
    ),
    pytest.param(
        _http_config(custom_headers=[{"name": "X", "value": _STEP_1, "secret": True}]),
        id="secret-header-value",
    ),
]


def test_upstream_orders_read_what_a_template_fill_binds() -> None:
    orders = _upstream(
        output_mode=FlowOutputMode.TEMPLATE_FILL,
        output_config={
            "template_asset_id": "0f1f0a52-6a3e-4c0e-9d8a-1f6f0c9d2b11",
            "bindings": {
                "beslut": _STEP_1,
                "namn": "{{ indata_text }}",
                "tom": "",
            },
        },
    )

    assert orders == [1]


def test_upstream_orders_read_a_template_fill_binding_by_step_label() -> None:
    orders = _upstream(
        output_mode=FlowOutputMode.TEMPLATE_FILL,
        output_config={"bindings": {"beslut": "{{ Beslutsunderlag }}"}},
        step_ref_mapping={"Beslutsunderlag": 2},
    )

    assert orders == [2]


@pytest.mark.parametrize("config", _HTTP_TEMPLATE_CARRIERS)
def test_upstream_orders_read_what_an_http_post_templates(
    config: dict[str, object],
) -> None:
    orders = _upstream(output_mode=FlowOutputMode.HTTP_POST, output_config=config)

    assert orders == [1]


@pytest.mark.parametrize("config", _HTTP_TEMPLATE_CARRIERS)
def test_upstream_orders_read_what_an_http_get_templates(
    config: dict[str, object],
) -> None:
    orders = _upstream(
        input_source=FlowInputSource.HTTP_GET,
        input_config=config,
    )

    assert orders == [1]


@pytest.mark.parametrize("config", _CREDENTIAL_FIELDS)
def test_upstream_orders_do_not_read_credential_fields_as_templates(
    config: dict[str, object],
) -> None:
    assert _upstream(output_mode=FlowOutputMode.HTTP_POST, output_config=config) == []
    assert _upstream(input_source=FlowInputSource.HTTP_GET, input_config=config) == []


def test_upstream_orders_join_input_prompt_and_config_reads() -> None:
    orders = _upstream(
        step_order=4,
        input_source=FlowInputSource.PREVIOUS_STEP,
        prompt_template="{{ step_1.output.text }}",
        output_mode=FlowOutputMode.HTTP_POST,
        output_config=_http_config(url="https://example.org/{{ step_2.status }}"),
    )

    assert orders == [1, 2, 3]


def test_upstream_orders_do_not_count_the_step_itself_or_later_steps() -> None:
    orders = _upstream(
        step_order=2,
        output_mode=FlowOutputMode.HTTP_POST,
        output_config=_http_config(
            url="https://example.org/{{ step_2.output.text }}/{{ step_3.output.text }}"
        ),
    )

    assert orders == []


def test_upstream_orders_read_the_previous_step_through_the_shorthand_in_config() -> (
    None
):
    body = {"mode": "text_template", "template": "{{ föregående_steg }}"}

    assert _upstream(
        input_source=FlowInputSource.HTTP_GET, input_config=_http_config(body=body)
    ) == [2]
    assert _upstream(
        output_mode=FlowOutputMode.TEMPLATE_FILL,
        output_config={"bindings": {"a": "{{ föregående_steg }}"}},
    ) == [2]


def test_upstream_orders_read_the_shorthand_in_a_webhook_as_the_steps_own_result() -> (
    None
):
    # The delivery context is built one step ahead, so the previous step of a
    # webhook is the step that produced the payload.
    orders = _upstream(
        output_mode=FlowOutputMode.HTTP_POST,
        output_config=_http_config(
            body={"mode": "text_template", "template": "{{ föregående_steg }}"}
        ),
    )

    assert orders == []


@pytest.mark.parametrize(
    ("mode", "source", "input_config", "output_config"),
    [
        pytest.param(
            FlowOutputMode.PASS_THROUGH,
            FlowInputSource.FLOW_INPUT,
            _http_config(url=f"https://example.org/{_STEP_1}"),
            {"bindings": {"a": _STEP_1}, **_http_config(url=_STEP_1)},
            id="config-of-a-mode-the-step-does-not-use",
        ),
        pytest.param(
            FlowOutputMode.TEMPLATE_FILL,
            FlowInputSource.PREVIOUS_STEP,
            _http_config(url=_STEP_1),
            {"bindings": {"a": "{{ indata_text }}"}, "template_name": _STEP_1},
            id="template-fill-reads-only-its-bindings",
        ),
        pytest.param(
            FlowOutputMode.HTTP_POST,
            FlowInputSource.FLOW_INPUT,
            None,
            _http_config(body={"mode": "auto", "template": _STEP_1}),
            id="body-template-the-mode-does-not-send",
        ),
        pytest.param(
            FlowOutputMode.HTTP_POST,
            FlowInputSource.HTTP_GET,
            _http_config(url="https://example.org/plain"),
            None,
            id="no-config-yet",
        ),
    ],
)
def test_upstream_orders_ignore_config_the_runtime_does_not_interpolate(
    mode: FlowOutputMode,
    source: FlowInputSource,
    input_config: dict[str, object] | None,
    output_config: dict[str, object] | None,
) -> None:
    orders = _upstream(
        input_source=source,
        output_mode=mode,
        input_config=input_config,
        output_config=output_config,
    )

    # Only the input source reads a step here: the previous one.
    assert orders == ([2] if source is FlowInputSource.PREVIOUS_STEP else [])


@pytest.mark.parametrize(
    ("mode", "source", "input_config", "output_config"),
    [
        pytest.param(
            FlowOutputMode.TEMPLATE_FILL,
            FlowInputSource.FLOW_INPUT,
            None,
            {"bindings": [_STEP_1]},
            id="bindings-not-an-object",
        ),
        pytest.param(
            FlowOutputMode.TEMPLATE_FILL,
            FlowInputSource.FLOW_INPUT,
            None,
            {"bindings": {"a": {"nested": _STEP_1}}},
            id="binding-not-a-string",
        ),
        pytest.param(
            FlowOutputMode.HTTP_POST,
            FlowInputSource.FLOW_INPUT,
            None,
            {"url": f"https://example.org/{_STEP_1}"},
            id="http-post-without-authored-shape",
        ),
        pytest.param(
            FlowOutputMode.PASS_THROUGH,
            FlowInputSource.HTTP_GET,
            _http_config(timeout_seconds="soon", url=_STEP_1),
            None,
            id="http-get-config-that-does-not-parse",
        ),
    ],
)
def test_upstream_orders_fail_closed_on_config_they_cannot_read(
    mode: FlowOutputMode,
    source: FlowInputSource,
    input_config: dict[str, object] | None,
    output_config: dict[str, object] | None,
) -> None:
    # The lineage cannot tell what an unreadable config would read, so the step
    # counts as reading every earlier step; the validators name the defect.
    orders = _upstream(
        step_order=4,
        input_source=source,
        output_mode=mode,
        input_config=input_config,
        output_config=output_config,
    )

    assert orders == [1, 2, 3]


def test_upstream_orders_fail_closed_on_an_unknown_output_mode() -> None:
    with pytest.raises(ValueError):
        _upstream(output_mode="sideways")


def test_input_orders_do_not_read_config_channels() -> None:
    # What reaches the step's model: the input and the prompt. Citation
    # inheritance is built on this, and a config read never reaches the model.
    assert (
        resolve_step_input_orders(
            input_source=FlowInputSource.FLOW_INPUT,
            step_order=3,
            input_bindings=None,
            prompt_template=None,
            step_ref_mapping={},
            max_prior_step_order=2,
        )
        == []
    )
