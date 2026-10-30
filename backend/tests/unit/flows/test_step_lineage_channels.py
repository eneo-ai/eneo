"""The per-channel reads of a step (``step_reads_by_channel``) and the merged
resolvers built on them: the union over the channels is what the resolvers
answered before the split, on every fixture shape of the merged suite."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from eneo.flows.enums import FlowInputSource, FlowOutputMode
from eneo.flows.step_lineage import (
    INPUT_SOURCE_READ_SITE,
    PROMPT_READ_SITE_PREFIX,
    FormFieldRead,
    StepRead,
    resolve_step_input_orders,
    resolve_step_upstream_orders,
    step_form_field_reads,
    step_reads_by_channel,
)

_STEP_1 = "{{ step_1.output.text }}"
_TOOL_IDS = {
    "mcp_server_id": "8f2f0a2e-51f5-4c53-9d0c-0c1a2b3c4d5e",
    "tool_id": "0b6a7c1d-93e4-4f0a-8a55-6d7e8f9a0b1c",
}


def _http_config(**fields: object) -> dict[str, object]:
    return {"url": "https://example.org/hook", "auth": {"mode": "none"}, **fields}


Shape = dict[str, Any]


def _shape(
    *,
    step_order: int = 4,
    input_source: FlowInputSource | str = FlowInputSource.FLOW_INPUT,
    input_bindings: Mapping[str, object] | None = None,
    prompt_template: str | None = None,
    output_mode: FlowOutputMode | str = FlowOutputMode.PASS_THROUGH,
    input_config: dict[str, object] | None = None,
    output_config: dict[str, object] | None = None,
    step_ref_mapping: dict[str, int] | None = None,
    max_prior_step_order: int | None = None,
) -> Shape:
    return {
        "input_source": input_source,
        "step_order": step_order,
        "input_bindings": input_bindings,
        "prompt_template": prompt_template,
        "output_mode": output_mode,
        "input_config": input_config,
        "output_config": output_config,
        "step_ref_mapping": step_ref_mapping or {},
        "max_prior_step_order": (
            step_order - 1 if max_prior_step_order is None else max_prior_step_order
        ),
    }


# Every fixture shape of the merged suite (tests/unittests/flows), plus the
# shapes the split adds: a question next to source refs, a question with a
# dangling brace, structured paths, labels.
_SHAPES = [
    pytest.param(
        _shape(
            input_source="all_previous_steps",
            input_bindings={"question": "Samtal: {{ step_2.output.text }}"},
            prompt_template="Bakgrund: {{ step_1.output.text }}",
        ),
        id="question-and-prompt",
    ),
    pytest.param(
        _shape(
            step_order=3,
            input_source="previous_step",
            input_bindings={"question": "Sammanfatta."},
            prompt_template="Bakgrund: {{ step_1.output.text }}",
        ),
        id="question-without-a-step-and-prompt",
    ),
    pytest.param(
        _shape(
            step_order=3,
            input_bindings={"question": "Samtal: {{ föregående_steg }}"},
        ),
        id="shorthand-in-the-question",
    ),
    pytest.param(
        _shape(
            step_order=3,
            input_bindings={"question": "Sammanfatta."},
            prompt_template="Bakgrund: {{ föregående_steg }}",
        ),
        id="shorthand-in-the-prompt",
    ),
    pytest.param(
        _shape(
            step_order=1,
            input_bindings={"question": "{{ föregående_steg }}"},
            prompt_template="{{ föregående_steg }}",
        ),
        id="shorthand-on-the-first-step",
    ),
    *(
        pytest.param(_shape(step_order=3, input_source=source), id=source.value)
        for source in FlowInputSource
    ),
    *(
        pytest.param(_shape(step_order=1, input_source=source), id=f"first-{source}")
        for source in (
            FlowInputSource.PREVIOUS_STEP,
            FlowInputSource.ALL_PREVIOUS_STEPS,
        )
    ),
    pytest.param(
        _shape(
            step_order=3,
            input_source=FlowInputSource.PREVIOUS_STEP,
            prompt_template="Bakgrund: {{ step_1.output.text }}",
        ),
        id="previous-step-and-prompt",
    ),
    pytest.param(
        _shape(
            step_order=3,
            output_mode=FlowOutputMode.TEMPLATE_FILL,
            output_config={
                "template_asset_id": "0f1f0a52-6a3e-4c0e-9d8a-1f6f0c9d2b11",
                "bindings": {"beslut": _STEP_1, "namn": "{{ indata_text }}", "tom": ""},
            },
        ),
        id="template-fill-bindings",
    ),
    pytest.param(
        _shape(
            step_order=3,
            output_mode=FlowOutputMode.TEMPLATE_FILL,
            output_config={"bindings": {"beslut": "{{ Beslutsunderlag }}"}},
            step_ref_mapping={"Beslutsunderlag": 2},
        ),
        id="template-fill-by-label",
    ),
    pytest.param(
        _shape(
            step_order=3,
            output_mode=FlowOutputMode.HTTP_POST,
            output_config=_http_config(
                url=f"https://example.org/{_STEP_1}",
                custom_headers=[{"name": "X-Text", "value": _STEP_1}],
                body={"mode": "json_template", "template": f'{{"t": "{_STEP_1}"}}'},
            ),
        ),
        id="http-post-templates",
    ),
    pytest.param(
        _shape(
            step_order=3,
            input_source=FlowInputSource.HTTP_GET,
            input_config=_http_config(
                auth={"mode": "basic_auth", "username": _STEP_1, "password": "p"}
            ),
        ),
        id="http-get-templates",
    ),
    pytest.param(
        _shape(
            step_order=3,
            output_mode=FlowOutputMode.HTTP_POST,
            output_config=_http_config(auth={"mode": "bearer_token", "token": _STEP_1}),
        ),
        id="credential-is-no-template",
    ),
    pytest.param(
        _shape(
            input_source=FlowInputSource.PREVIOUS_STEP,
            prompt_template="{{ step_1.output.text }}",
            output_mode=FlowOutputMode.HTTP_POST,
            output_config=_http_config(url="https://example.org/{{ step_2.status }}"),
        ),
        id="input-prompt-and-config",
    ),
    pytest.param(
        _shape(
            step_order=2,
            output_mode=FlowOutputMode.HTTP_POST,
            output_config=_http_config(
                url="https://example.org/{{ step_2.output.text }}/{{ step_3.output.text }}"
            ),
        ),
        id="self-and-later-steps",
    ),
    pytest.param(
        _shape(
            step_order=3,
            input_source=FlowInputSource.HTTP_GET,
            input_config=_http_config(
                body={"mode": "text_template", "template": "{{ föregående_steg }}"}
            ),
        ),
        id="shorthand-in-http-get",
    ),
    pytest.param(
        _shape(
            step_order=3,
            output_mode=FlowOutputMode.HTTP_POST,
            output_config=_http_config(
                body={"mode": "text_template", "template": "{{ föregående_steg }}"}
            ),
        ),
        id="shorthand-in-a-webhook",
    ),
    pytest.param(
        _shape(
            step_order=3,
            input_source=FlowInputSource.PREVIOUS_STEP,
            output_mode=FlowOutputMode.TEMPLATE_FILL,
            input_config=_http_config(url=_STEP_1),
            output_config={
                "bindings": {"a": "{{ indata_text }}"},
                "template_name": _STEP_1,
            },
        ),
        id="config-of-an-unused-mode",
    ),
    pytest.param(
        _shape(
            output_mode=FlowOutputMode.TEMPLATE_FILL,
            output_config={"bindings": [_STEP_1]},
        ),
        id="unreadable-bindings",
    ),
    pytest.param(
        _shape(
            output_mode=FlowOutputMode.HTTP_POST,
            output_config={"url": f"https://example.org/{_STEP_1}"},
        ),
        id="unreadable-http-post",
    ),
    pytest.param(
        _shape(
            input_source=FlowInputSource.HTTP_GET,
            input_config=_http_config(timeout_seconds="soon", url=_STEP_1),
        ),
        id="unreadable-http-get",
    ),
    pytest.param(
        _shape(
            input_source=FlowInputSource.TOOL,
            input_config={
                "tool": {
                    **_TOOL_IDS,
                    "arguments": {"days": "{{ step_1.output.structured.days }}"},
                }
            },
        ),
        id="tool-argument",
    ),
    pytest.param(
        _shape(
            input_source=FlowInputSource.TOOL,
            input_config={"tool": {**_TOOL_IDS, "arguments": {"q": f"day {_STEP_1}"}}},
        ),
        id="unreadable-tool-argument",
    ),
    pytest.param(
        _shape(input_source=FlowInputSource.TOOL, input_config=None),
        id="absent-tool-config",
    ),
    pytest.param(
        _shape(
            input_config={
                "tool": {**_TOOL_IDS, "arguments": {"days": "{{ step_1.output.text }}"}}
            }
        ),
        id="leftover-tool-config",
    ),
    pytest.param(
        _shape(
            step_order=3,
            input_bindings={"source_refs": [{"step_ref": "step_02", "output": "text"}]},
        ),
        id="source-ref-spelled-with-a-zero",
    ),
    pytest.param(
        _shape(
            input_bindings={
                "question": "Jämför {{ step_1.output.text }} med:",
                "source_refs": [
                    {"step_ref": "step_2", "output": "structured", "field_path": "a.b"},
                    {"step_ref": "step_3", "output": "text", "label": "Beslut"},
                ],
            },
            prompt_template="{{ step_1.output.structured.a }} och {{ step_3.output }}",
        ),
        id="question-source-refs-and-prompt",
    ),
    pytest.param(
        _shape(
            input_bindings={
                "question": "Öppen klammer {{",
                "source_refs": [{"step_ref": "step_1", "output": "text"}],
            }
        ),
        id="dangling-brace-before-a-source-ref",
    ),
    pytest.param(
        _shape(
            input_bindings={"question": "{{ Sammanfattning }}"},
            prompt_template="{{ Sammanfattning.output.structured.x.y }}",
            step_ref_mapping={"Sammanfattning": 2},
        ),
        id="label-reads",
    ),
]


@pytest.mark.parametrize("shape", _SHAPES)
def test_the_union_of_the_channels_is_the_merged_resolvers(shape: Shape) -> None:
    reads = step_reads_by_channel(**shape)

    model_orders = sorted(
        {read.step_order for read in reads if read.channel in ("input", "prompt")}
    )
    assert model_orders == resolve_step_input_orders(
        **{
            key: shape[key]
            for key in (
                "input_source",
                "step_order",
                "input_bindings",
                "prompt_template",
                "step_ref_mapping",
                "max_prior_step_order",
            )
        }
    )
    assert sorted({read.step_order for read in reads}) == resolve_step_upstream_orders(
        **shape
    )


@pytest.mark.parametrize("shape", _SHAPES)
def test_every_read_names_a_step_with_a_result(shape: Shape) -> None:
    for read in step_reads_by_channel(**shape):
        assert 1 <= read.step_order <= max(shape["max_prior_step_order"], 1)
        assert read.channel in ("input", "prompt", "config")
        assert read.site


def test_previous_step_is_one_input_read_of_the_step_before() -> None:
    reads = step_reads_by_channel(
        **_shape(step_order=3, input_source=FlowInputSource.PREVIOUS_STEP)
    )

    assert reads == (StepRead("input", 2, (), INPUT_SOURCE_READ_SITE),)


def test_all_previous_steps_is_one_input_read_per_earlier_step() -> None:
    reads = step_reads_by_channel(
        **_shape(step_order=4, input_source=FlowInputSource.ALL_PREVIOUS_STEPS)
    )

    assert reads == tuple(
        StepRead("input", order, (), INPUT_SOURCE_READ_SITE) for order in (1, 2, 3)
    )


def test_underlag_reads_are_sited_at_the_question_and_each_source_ref() -> None:
    reads = step_reads_by_channel(
        **_shape(
            input_source=FlowInputSource.PREVIOUS_STEP,
            input_bindings={
                "question": "Jämför {{ step_1.output.text }} med:",
                "source_refs": [
                    {"step_ref": "step_2", "output": "structured", "field_path": "a.b"},
                    {"step_ref": "step_3", "output": "structured"},
                ],
            },
        )
    )

    # Underlag replaces the implicit input: no read of ``input_source``.
    assert reads == (
        StepRead("input", 1, (), "input_bindings.question"),
        StepRead("input", 2, ("structured", "a", "b"), "input_bindings.source_refs[0]"),
        StepRead("input", 3, ("structured",), "input_bindings.source_refs[1]"),
    )


def test_prompt_reads_are_sited_as_the_runtime_records_their_edges() -> None:
    reads = step_reads_by_channel(
        **_shape(
            prompt_template=(
                "Text: {{ step_1.output.text }}\n"
                "Fält: {{ step_2.output.structured.summary }}\n"
                "Allt: {{step_3.output.structured}} {{ föregående_steg }}"
            ),
        )
    )

    assert reads == (
        StepRead("prompt", 1, (), f"{PROMPT_READ_SITE_PREFIX}step_1.output.text"),
        StepRead(
            "prompt",
            2,
            ("structured", "summary"),
            f"{PROMPT_READ_SITE_PREFIX}step_2.output.structured.summary",
        ),
        StepRead(
            "prompt",
            3,
            ("structured",),
            f"{PROMPT_READ_SITE_PREFIX}step_3.output.structured",
        ),
        StepRead("prompt", 3, (), f"{PROMPT_READ_SITE_PREFIX}föregående_steg"),
    )


def test_config_reads_name_their_column_and_path() -> None:
    reads = step_reads_by_channel(
        **_shape(
            input_source=FlowInputSource.TOOL,
            input_config={
                "tool": {
                    **_TOOL_IDS,
                    "arguments": {"days": "{{ step_1.output.structured.days }}"},
                }
            },
            output_mode=FlowOutputMode.HTTP_POST,
            output_config=_http_config(
                url=f"https://example.org/{_STEP_1}",
                custom_headers=[
                    {"name": "X-Text", "value": "{{ step_2.output.text }}"}
                ],
            ),
        )
    )

    assert reads == (
        StepRead("config", 1, (), "output_config.url"),
        StepRead("config", 2, (), "output_config.custom_headers.0.value"),
        StepRead(
            "config",
            1,
            ("structured", "days"),
            "input_config.tool.arguments.days",
        ),
    )


def test_an_unreadable_config_reads_every_earlier_step_at_its_column() -> None:
    reads = step_reads_by_channel(
        **_shape(
            output_mode=FlowOutputMode.TEMPLATE_FILL,
            output_config={"bindings": [_STEP_1]},
        )
    )

    assert reads == tuple(
        StepRead("config", order, (), "output_config") for order in (1, 2, 3)
    )


def test_config_reads_never_count_as_model_reads() -> None:
    reads = step_reads_by_channel(
        **_shape(
            output_mode=FlowOutputMode.TEMPLATE_FILL,
            output_config={"bindings": {"a": _STEP_1}},
        )
    )

    assert [read.channel for read in reads] == ["config"]
    assert (
        resolve_step_input_orders(
            **{
                key: value
                for key, value in _shape().items()
                if key not in ("output_mode", "input_config", "output_config")
            }
        )
        == []
    )


@pytest.mark.parametrize("unknown", [str(FlowInputSource.PREVIOUS_STEP), "", None])
def test_reads_fail_closed_on_an_unknown_input_source(unknown: object) -> None:
    with pytest.raises(ValueError):
        step_reads_by_channel(**_shape(input_source=unknown))  # pyright: ignore[reportArgumentType]


def test_reads_fail_closed_on_an_unknown_output_mode() -> None:
    with pytest.raises(ValueError):
        step_reads_by_channel(**_shape(output_mode="sideways"))


_FIELDS = ("kommun", "arende")


def _field_reads(**shape: Any) -> tuple[FormFieldRead, ...]:
    values = _shape(**shape)
    values.pop("max_prior_step_order")
    return step_form_field_reads(**values, form_field_names=_FIELDS)


def test_form_fields_are_read_per_channel_by_path_and_bare_name() -> None:
    reads = _field_reads(
        input_bindings={"question": "{{ flow_input.kommun }}"},
        prompt_template="Ärende: {{ arende }}",
        output_mode=FlowOutputMode.TEMPLATE_FILL,
        output_config={"bindings": {"ort": "{{ flow.input.kommun }}"}},
    )

    assert reads == (
        FormFieldRead("input", "kommun", "input_bindings.question"),
        FormFieldRead("prompt", "arende", f"{PROMPT_READ_SITE_PREFIX}arende"),
        FormFieldRead("config", "kommun", "output_config.bindings.ort"),
    )


@pytest.mark.parametrize(
    "shape",
    [
        pytest.param({}, id="flow-input-without-underlag"),
        pytest.param(
            {"input_bindings": {"question": "{{ flow_input }}"}}, id="whole-template"
        ),
        pytest.param(
            {
                "input_source": FlowInputSource.PREVIOUS_STEP,
                "output_mode": FlowOutputMode.TEMPLATE_FILL,
                "output_config": {"bindings": "not an object"},
            },
            id="unreadable-config",
        ),
    ],
)
def test_the_whole_run_input_reads_every_form_field(shape: dict[str, Any]) -> None:
    assert {read.field for read in _field_reads(**shape)} == set(_FIELDS)


def test_speaker_mapping_reads_the_form_fields_its_configuration_names() -> None:
    reads = _field_reads(
        input_source=FlowInputSource.PREVIOUS_STEP,
        output_mode=FlowOutputMode.SPEAKER_MAPPING,
        output_config={
            "speaker_mapping": {
                "participants_field": "kommun",
                "speaker_count_field": "arende",
            }
        },
    )

    assert reads == (
        FormFieldRead(
            "config", "kommun", "output_config.speaker_mapping.participants_field"
        ),
        FormFieldRead(
            "config", "arende", "output_config.speaker_mapping.speaker_count_field"
        ),
    )


def test_no_form_field_is_read_by_a_step_reading_only_steps() -> None:
    assert (
        _field_reads(
            input_source=FlowInputSource.PREVIOUS_STEP,
            prompt_template=_STEP_1,
        )
        == ()
    )
