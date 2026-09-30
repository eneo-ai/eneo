from __future__ import annotations

import pytest

from eneo.flows.ai_builder.ai_builder_step_reads import (
    ReadChannel,
    ReadSite,
    StepRead,
    step_reads,
    step_template_sites,
)
from eneo.flows.ai_builder.ai_builder_validation_references import (
    iter_step_templates,
)
from eneo.flows.domain.flow import FlowRunStatus
from eneo.flows.flow_authoring_spec import AssistantSpec, StepSpec
from eneo.flows.input_binding_contract_rules import SourceRefBinding
from tests.unittests.flows.test_typed_io_executor import (
    _build_executor,
    _completed_step_result,
    _run,
    _runtime_step,
)

(
    TEXT,
    STRUCTURED,
    STRUCTURED_ELSE_TEXT,
    STEP_OTHER,
    FORM_FIELD,
    RUN_INPUT,
    RUN_INPUT_ALIAS,
    STEP_INPUT,
) = ReadChannel
IMPLICIT, SOURCE_REF, QUESTION, INSTRUCTIONS, OUTPUT_CONFIG = ReadSite
STEP_REFS = {"step_a": 1, "step_b": 2, "step_c": 3, "step_1": 1, "step_2": 2}
FORMS = {"audience", "subject", "tags"}


def _step(instructions: str = "Svara.", **fields: object) -> StepSpec:
    return StepSpec.model_validate(
        {
            "plan_step_ref": "step_c",
            "name": "C",
            "assistant_spec": AssistantSpec(instructions=instructions),
            "input_source": "previous_step",
            **fields,
        }
    )


def _reads(step: StepSpec, order: int = 3) -> tuple[StepRead, ...]:
    return step_reads(step, order=order, step_refs=STEP_REFS, form_field_names=FORMS)


def test_every_site_is_read_in_order_with_its_origin():
    step = _step(
        "{{ step_b.output.structured.beslut.ansvarig }} {{ step_1.status }} "
        "{{ indata_text }} {{ datum }} {{ step_input.text }} {{ form.audience }}",
        input_bindings={
            "question": "{{ step_a.output.text }} {{ audience }} {{ flow_input.subject }}",
            "source_refs": [
                {
                    "step_ref": "step_a",
                    "output": "structured",
                    "field_path": "documents.*.title",
                    "label": "Titlar",
                },
                {"step_ref": "step_b", "output": "text"},
            ],
        },
        output_mode="template_fill",
        output_type="docx",
        output_config={
            "bindings": {
                "brodtext": "{{ föregående_steg }}",
                "allt": "{{ flow_input }}",
            }
        },
    )

    reads = _reads(step)

    assert [
        (read.producer_order, read.channel, read.path, read.site, read.positional)
        for read in reads
    ] == [
        (1, STRUCTURED, ("documents", "*", "title"), SOURCE_REF, False),
        (2, TEXT, (), SOURCE_REF, False),
        (2, STRUCTURED, ("beslut", "ansvarig"), INSTRUCTIONS, False),
        (1, STEP_OTHER, ("status",), INSTRUCTIONS, False),
        (None, RUN_INPUT_ALIAS, ("indata_text",), INSTRUCTIONS, False),
        (None, STEP_INPUT, ("text",), INSTRUCTIONS, False),
        (1, TEXT, (), QUESTION, False),
        (None, FORM_FIELD, ("audience",), QUESTION, False),
        (None, FORM_FIELD, ("subject",), QUESTION, False),
        (2, TEXT, (), OUTPUT_CONFIG, True),
        (None, RUN_INPUT, (), OUTPUT_CONFIG, False),
    ]
    assert reads[0].origin == SourceRefBinding(
        "step_a", "structured", ("documents", "*", "title"), label="Titlar"
    )
    assert [read.origin for read in reads[2:]] == [
        "step_b.output.structured.beslut.ansvarig",
        "step_1.status",
        "indata_text",
        "step_input.text",
        "step_a.output.text",
        "audience",
        "flow_input.subject",
        "föregående_steg",
        "flow_input",
    ]


@pytest.mark.parametrize(
    ("input_source", "input_type", "order", "expected"),
    [
        ("flow_input", "text", 2, [(None, RUN_INPUT, False)]),
        ("previous_step", "text", 3, [(2, TEXT, True)]),
        ("previous_step", "json", 3, [(2, STRUCTURED_ELSE_TEXT, True)]),
        ("previous_step", "text", 1, []),
        ("all_previous_steps", "json", 3, [(1, TEXT, True), (2, TEXT, True)]),
    ],
)
def test_the_implicit_read_takes_the_channel_the_runtime_delivers(
    input_source, input_type, order, expected
):
    reads = _reads(_step(input_source=input_source, input_type=input_type), order)

    assert [
        (read.producer_order, read.channel, read.positional) for read in reads
    ] == expected
    assert all(read.site is IMPLICIT and read.path == () for read in reads)


def _upload(input_format: str, *, required: bool = True) -> dict[str, object]:
    return {
        "runtime_input": {
            "enabled": True,
            "required": required,
            "input_format": input_format,
        }
    }


@pytest.mark.parametrize(
    ("fields", "implicit"),
    [
        ({"input_bindings": {"question": "Svara kort."}}, []),
        (
            {
                "input_bindings": {
                    "source_refs": [{"step_ref": "step_a", "output": "text"}]
                }
            },
            [],
        ),
        (
            {
                "input_source": "flow_input",
                "input_type": "audio",
                "output_mode": "transcribe_only",
                "input_config": _upload("audio"),
            },
            [STEP_INPUT],
        ),
        (
            {"input_source": "flow_input", "input_config": _upload("document")},
            [RUN_INPUT, STEP_INPUT],
        ),
        (
            {
                "input_bindings": {"question": "Svara kort."},
                "input_config": _upload("document"),
            },
            [STEP_INPUT],
        ),
    ],
)
def test_underlag_replaces_the_implicit_chain_but_not_the_step_upload(fields, implicit):
    reads = _reads(_step(**fields))

    assert [read.channel for read in reads if read.site is IMPLICIT] == implicit


@pytest.mark.parametrize(("order", "producer"), [(1, None), (3, 2)])
def test_foregaende_steg_reads_the_step_before_by_position(order, producer):
    step = _step("{{ föregående_steg }}", input_bindings={"question": "Svara."})

    (read,) = _reads(step, order)

    assert read == StepRead(producer, TEXT, (), INSTRUCTIONS)
    assert read.positional
    assert read.origin == "föregående_steg"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("structured", "selector"),
    [({"k": 1}, ("output", "structured")), (None, ("output", "text"))],
)
async def test_a_json_step_reads_its_predecessor_structured_else_text(
    user, structured, selector
):
    (read,) = _reads(_step(input_type="json"), order=2)
    assert read.channel is STRUCTURED_ELSE_TEXT

    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    prior = [
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=1,
            text='{"k": 1}',
            structured=structured,
        )
    ]
    resolved = await executor._resolve_step_input(
        step=_runtime_step(
            step_order=2, input_source="previous_step", input_type="json"
        ),
        context=executor.variable_resolver.build_context(run.input_payload_json, prior),
        run=run,
        prior_results=prior,
    )

    assert [edge.source.selector.path for edge in resolved.edges] == [selector]


@pytest.mark.parametrize(
    ("expression", "channel", "path"),
    [
        ("flow_input", RUN_INPUT, ()),
        ("flow", RUN_INPUT_ALIAS, ("flow",)),
        ("flow.input", RUN_INPUT, ()),
        ("flow_input.text", RUN_INPUT, ("text",)),
        ("flow.input.text", RUN_INPUT, ("text",)),
        ("flow_input.transkribering", RUN_INPUT, ("transkribering",)),
        ("indata_text", RUN_INPUT_ALIAS, ("indata_text",)),
        ("indata_json", RUN_INPUT_ALIAS, ("indata_json",)),
        ("indata_json.beslut", RUN_INPUT_ALIAS, ("indata_json", "beslut")),
        ("transkribering", RUN_INPUT_ALIAS, ("transkribering",)),
        ("step_input.text", STEP_INPUT, ("text",)),
        ("step_input.file_ids.0", STEP_INPUT, ("file_ids", "0")),
    ],
)
def test_run_input_reads_keep_a_key_an_alias_and_the_step_input_apart(
    expression, channel, path
):
    (read,) = _reads(_step(input_bindings={"question": "{{ " + expression + " }}"}))

    assert read == StepRead(None, channel, path, QUESTION)


def test_a_form_field_read_keeps_its_whole_path():
    # tags.0 and tags.1 read different list items of one form field.
    step = _step(
        "{{ flow_input.tags.0 }} {{ flow.input.tags.1 }}",
    )

    assert [(read.channel, read.path) for read in _reads(step)[:2]] == [
        (FORM_FIELD, ("tags", "0")),
        (FORM_FIELD, ("tags", "1")),
    ]


@pytest.mark.parametrize("expression", ["flow_input.input", "flow.input.input"])
def test_a_form_field_named_input_is_read_as_that_field(expression):
    step = _step(input_bindings={"question": "{{ " + expression + " }}"})

    (read,) = step_reads(
        step, order=3, step_refs=STEP_REFS, form_field_names=FORMS | {"input"}
    )

    assert (read.channel, read.path) == (FORM_FIELD, ("input",))


@pytest.mark.parametrize("step_ref", ["step_2", "step_02", "step_\u0662", "step_b"])
def test_a_source_ref_reads_the_producer_the_runtime_reads(step_ref: str):
    step = _step(
        input_bindings={"source_refs": [{"step_ref": step_ref, "output": "text"}]}
    )

    (read,) = _reads(step)

    assert (read.producer_order, read.site) == (2, SOURCE_REF)


def test_a_step_name_the_flow_does_not_resolve_has_no_producer():
    step = _step(
        "{{ step_x.output.text }}",
        input_bindings={"source_refs": [{"step_ref": "step_zz", "output": "text"}]},
    )

    assert [(read.producer_order, read.site) for read in _reads(step)] == [
        (None, SOURCE_REF),
        (None, INSTRUCTIONS),
    ]


def test_template_sites_are_the_carriers_validation_iterates():
    step = _step("Instruktion", input_bindings={"question": "Å {{ audience }}"})

    assert step_template_sites(step) == [
        (INSTRUCTIONS, "Instruktion"),
        (QUESTION, '{"question": "Å {{ audience }}"}'),
    ]
    assert iter_step_templates(step) == [
        template for _, template in step_template_sites(step)
    ]


@pytest.mark.parametrize("output_mode", ["pass_through", "compose_text"])
def test_an_output_config_the_runtime_does_not_interpolate_is_no_template_site(
    output_mode: str,
):
    step = _step(output_mode=output_mode, output_config={"note": "{{ step_a }}"})

    assert step_template_sites(step) == [(INSTRUCTIONS, "Svara.")]
    assert [read.site for read in _reads(step)] == [IMPLICIT]


def test_a_template_fill_is_read_at_its_bindings_only():
    step = _step(
        output_mode="template_fill",
        output_type="docx",
        output_config={
            "bindings": {"a": "{{ step_a.output.text }}", "b": "Fast text"},
            "note": "{{ step_b }}",
        },
    )

    assert step_template_sites(step) == [
        (INSTRUCTIONS, "Svara."),
        (OUTPUT_CONFIG, "{{ step_a.output.text }}"),
        (OUTPUT_CONFIG, "Fast text"),
    ]


def test_validation_judges_a_template_fill_binding_and_not_a_literal_key():
    from eneo.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
    from eneo.flows.ai_builder.ai_builder_validation_references import (
        validate_variable_references,
    )
    from eneo.flows.flow_authoring_spec import FlowDraftSpecCore

    def validate(**fields: object) -> SpecValidationResult:
        first = _step().model_copy(update={"plan_step_ref": "step_a", "name": "A"})
        reader = _step(**fields).model_copy(update={"plan_step_ref": "step_b"})
        later = _step().model_copy(update={"plan_step_ref": "step_late", "name": "L"})
        result = SpecValidationResult()
        validate_variable_references(
            FlowDraftSpecCore(flow_name="F", steps=[first, reader, later]), result
        )
        return result

    forward = "{{ step_3.output.text }}"
    literal = validate(output_config={"note": forward})
    bound = validate(
        output_mode="template_fill",
        output_type="docx",
        output_config={"bindings": {"a": forward}},
    )

    assert literal.valid, literal.errors
    assert not bound.valid
    assert [error.code for error in bound.errors] == ["future_step_reference"]
