"""Steps the AI Builder proposes that read an MCP tool, in create and edit.

The planner names a tool of the turn's catalogue by its ref and, per
argument, a fixed value, a run-form field or an earlier step's field; the
compiler writes the editor's tool configuration, and the final spec meets
publish's own checks. Every server and tool here is a neutral fake.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from eneo.completion_models.domain.model_capacity import ModelCapacity
from eneo.flows.ai_builder import ai_builder_planner_request_preparation
from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_compiled_spec_preparation import (
    prepare_compiled_spec_for_session,
)
from eneo.flows.ai_builder.ai_builder_create_compile_context import (
    CreateCompileContext,
)
from eneo.flows.ai_builder.ai_builder_create_compiler import (
    compile_create_intent_to_spec,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_edit_compiler import compile_edit_proposal
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
)
from eneo.flows.ai_builder.ai_builder_planner_request_preparation import (
    ProposalPrepared,
    build_proposal_prepared,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    AddStep,
    FlowInputFieldIntent,
    ModifyExistingStep,
    OrderedEditProposal,
    SemanticStepIntent,
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CorrectableFailure,
    ProposalAnswer,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import RequirementsState
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_tool_catalog import (
    TOOL_REF_HEX_DIGITS,
    AIBuilderToolCatalogListed,
    AIBuilderToolCatalogTooLarge,
    fit_tool_catalog_projection,
    tool_options_with_refs,
    tool_ref,
)
from eneo.flows.ai_builder.ai_builder_tool_use import (
    RunFormFieldShape,
    ToolUseIntent,
    tool_argument_form_field,
)
from eneo.flows.ai_builder.ai_builder_tool_validation import tool_use_ref_outcome
from eneo.flows.ai_builder.ai_builder_tools import (
    build_propose_flow_tool_schema,
    validate_propose_flow_tool_arguments,
)
from eneo.flows.ai_builder.planning_state import (
    ConfirmedRuntimeMetadataField,
    PlanningState,
    RuntimeMetadataFieldPurpose,
)
from eneo.flows.application.flow_authoring_snapshot import UnsupportedSavedStepsError
from eneo.flows.application.flow_draft_materialization import (
    ALL_STEP_COLUMNS,
    compile_flow_draft_changeset,
)
from eneo.flows.application.flow_tool_options import FlowToolOption, FlowToolOptions
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshot
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.domain.tool_input import TOOL_INPUT_CONFIG_KEY, ToolInputConfig
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from eneo.flows.flow_authoring_variable_rewriting import (
    flow_step_validation_views_from_draft_spec,
)
from eneo.flows.flow_variable_definitions import form_field_reference_expression
from eneo.flows.input_binding_contract_rules import (
    SourceRefBinding,
    effective_question_binding,
)
from eneo.flows.runtime import tool_argument_check
from eneo.mcp_servers.application.unattended_tool_use import UnattendedToolRefusal
from tests.unittests.flows.ai_builder.test_ai_builder_form_field_lifecycle import (
    _form_metadata,
)
from tests.unittests.flows.ai_builder.test_ai_builder_planner import _budget_policy
from tests.unittests.flows.ai_builder.test_ai_builder_unsupported_saved_steps import (
    _flow,
    _scoped_to,
    _step,
)

SERVER = UUID("3d1c9a52-0f4e-4a77-9a1e-5b6c7d8e9f01")
VALUES_TOOL = UUID("6a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d")
DETAILS_TOOL = UUID("7b2c3d4e-5f6a-4b7c-9d8e-0f1a2b3c4d5e")
OFF_TOOL = UUID("8c3d4e5f-6a7b-4c8d-ae9f-1a2b3c4d5e6f")
DATE = {"type": "string", "format": "date"}


def _option(
    tool_id: UUID,
    name: str,
    schema: dict[str, object] | None,
    *,
    refusal: UnattendedToolRefusal | None = None,
    server_id: UUID = SERVER,
) -> FlowToolOption:
    return FlowToolOption(
        mcp_server_id=server_id,
        mcp_server_name="Data",
        mcp_server_security_level=None,
        tool_id=tool_id,
        tool_name=name,
        tool_description=f"Neutral fake tool {name}.",
        input_schema=schema,
        refusal=refusal,
    )


VALUES = _option(
    VALUES_TOOL,
    "values_by_day",
    {
        "type": "object",
        "properties": {
            "from_date": DATE,
            "to_date": DATE,
            "unit": {"type": "string", "enum": ["hour", "day"]},
        },
        "required": ["from_date", "to_date"],
        "additionalProperties": False,
    },
)
DETAILS = _option(
    DETAILS_TOOL,
    "details_for_days",
    {
        "type": "object",
        "properties": {"days": {"type": "array", "items": {"type": "string"}}},
        "required": ["days"],
    },
)
OFF = _option(
    OFF_TOOL,
    "archive",
    None,
    refusal=UnattendedToolRefusal.TOOL_SWITCHED_OFF_IN_SPACE,
)
VALUES_REF = tool_ref(SERVER, VALUES_TOOL)
DEPARTMENT = ConfirmedRuntimeMetadataField(
    value=FlowInputFieldIntent(
        variable_name="department", label="Avdelning", provenance="user_confirmed"
    ),
    purpose="whole_flow",
    structured_answer_message_id="message-1",
)
DETAILS_REF = tool_ref(SERVER, DETAILS_TOOL)
OFF_REF = tool_ref(SERVER, OFF_TOOL)


def _catalog(*options: FlowToolOption) -> AIBuilderResourceCatalog:
    return build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        tool_options=FlowToolOptions(
            options=list(options), security_classifications_enabled=False
        ),
    )


def _argument(name: str, source: str, **values: Any) -> dict[str, Any]:
    return {
        "name": name,
        "source": source,
        "value_json": None,
        "field_name": None,
        "field_label": None,
        "from_step": None,
        "field_path": None,
        **values,
    }


def _step_payload(
    name: str, tool_use: dict[str, Any] | None, *output: str
) -> dict[str, Any]:
    return {
        "name": name,
        "instructions": f"{name}.",
        "knowledge_refs": None,
        "citations_requested": False,
        "tool_use": tool_use,
        "output_fields": (
            [
                {
                    "name": field,
                    "field_type": "array",
                    "description": field,
                    "required": True,
                    "nullable": False,
                    "children": None,
                }
                for field in output
            ]
            or None
        ),
    }


def _two_tool_flow(
    days_path: str = "days", values_arguments: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "flow_name": "Avvikande dagar",
        "plan_rationale": "Hämta, välj dagar, hämta detaljer, skriv.",
        "steps": [
            _step_payload(
                "Hitta dagar",
                {
                    "use_ref": "values",
                    "tool_ref": VALUES_REF,
                    "alternative_refs": [],
                    "evidence_quote": None,
                    "arguments": values_arguments
                    or [
                        _argument(
                            "from_date",
                            "run_input",
                            field_name="from_date",
                            field_label="Från datum",
                        ),
                        _argument(
                            "to_date",
                            "run_input",
                            field_name="to_date",
                            field_label="Till datum",
                        ),
                        _argument("unit", "fixed", value_json='"day"'),
                    ],
                },
                "days",
            ),
            _step_payload(
                "Hämta detaljer",
                {
                    "use_ref": "details",
                    "tool_ref": DETAILS_REF,
                    "alternative_refs": [],
                    "evidence_quote": None,
                    "arguments": [
                        _argument(
                            "days", "earlier_step", from_step=1, field_path=days_path
                        )
                    ],
                },
            ),
            _step_payload("Skriv rapport", None),
        ],
    }


def _compile_create(
    arguments: dict[str, Any],
    catalog: AIBuilderResourceCatalog,
    *,
    confirmed: tuple[ConfirmedRuntimeMetadataField, ...] = (),
    **context: Any,
) -> FlowDraftSpecCore:
    validate_propose_flow_tool_arguments(
        arguments=arguments,
        tool_schema=build_propose_flow_tool_schema(
            resource_catalog=catalog, tool_refs=catalog.tools.listed_refs
        ),
    )
    return compile_create_intent_to_spec(
        parse_create_flow_intent_arguments(arguments),
        context=CreateCompileContext(
            **{
                "runtime_input_type": InputType.TEXT,
                "final_output_type": OutputType.TEXT,
                "runtime_input_fields": confirmed,
                **context,
            }
        ),
        tool_catalog=catalog.tools,
    )


def _prepare(
    spec: FlowDraftSpecCore,
    catalog: AIBuilderResourceCatalog,
    target_kind: TargetKind = TargetKind.CREATE,
    **kwargs: Any,
):
    return asyncio.run(
        prepare_compiled_spec_for_session(
            spec=spec,
            target_kind=target_kind,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=catalog,
            **kwargs,
        )
    )


def test_tool_refs_are_stable_and_resolve_beyond_the_tools_a_turn_lists() -> None:
    # Kills: a ref by list position (a tool the space adds moves the others),
    # resolution through the fitted projection only (a tool the budget cut
    # becomes unknown), a refused tool resolved as usable.
    small = _catalog(VALUES, OFF).tools
    grown = _catalog(_option(uuid4(), "aaa_first", None), VALUES, DETAILS, OFF).tools
    cut = fit_tool_catalog_projection(
        grown.projection,
        fits=lambda projection: isinstance(projection, AIBuilderToolCatalogListed)
        and len(projection.tools) == 1,
    )

    assert VALUES_REF in small.listed_refs and VALUES_REF in grown.listed_refs
    assert (
        VALUES_REF.startswith("tool_")
        and len(VALUES_REF) == len("tool_") + TOOL_REF_HEX_DIGITS
    )
    assert isinstance(cut, AIBuilderToolCatalogListed)
    assert DETAILS_REF not in [tool.ref for tool in cut.tools]
    assert replace(grown, projection=cut).resolve_ref(DETAILS_REF) == DETAILS
    unavailable = grown.resolve_ref(OFF_REF)
    assert not isinstance(unavailable, FlowToolOption) and unavailable is not None
    assert unavailable.reason is UnattendedToolRefusal.TOOL_SWITCHED_OFF_IN_SPACE
    assert grown.resolve_ref("tool_" + "0" * TOOL_REF_HEX_DIGITS) is None


def test_a_ref_is_a_function_of_its_tools_ids_even_when_two_tools_collide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Kills: refs lengthened when two tools of the space coincide (every
    # other tool's ref would change as the catalogue grows), and one of two
    # colliding tools silently shadowing the other.
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_tool_catalog.TOOL_REF_HEX_DIGITS", 1
    )
    options = [
        _option(UUID(int=index), f"tool_{index}", None) for index in range(1, 21)
    ]

    with_refs = tool_options_with_refs(options)

    by_ref: dict[str, list[FlowToolOption]] = {}
    for option in options:
        by_ref.setdefault(tool_ref(option.mcp_server_id, option.tool_id), []).append(
            option
        )
    assert any(len(sharing) > 1 for sharing in by_ref.values())
    assert any(len(sharing) == 1 for sharing in by_ref.values())
    assert dict((ref, option) for ref, option in with_refs) == {
        ref: sharing[0] for ref, sharing in by_ref.items() if len(sharing) == 1
    }


def test_a_step_offers_tool_use_only_with_the_refs_the_turn_names() -> None:
    # Kills: the property offered with no tool to name, an enum that is not
    # the turn's refs.
    catalog = _catalog(VALUES, OFF)

    def step_properties(refs: tuple[str, ...]) -> dict[str, Any]:
        schema = build_propose_flow_tool_schema(
            resource_catalog=catalog, tool_refs=refs
        )
        return schema["function"]["parameters"]["properties"]["steps"]["items"][
            "properties"
        ]

    assert "tool_use" not in step_properties(())
    offered = step_properties(catalog.tools.listed_refs)["tool_use"]
    assert offered["properties"]["tool_ref"]["enum"] == [VALUES_REF, OFF_REF]


def test_a_create_plan_reads_tools_through_the_editors_tool_configuration() -> None:
    # Kills: hand-written templates instead of the owners', a first step
    # forced to read the run input, a main-text field added to a run form
    # nobody's text is read from, an argument field typed as text, plan
    # refs left in a tool argument at apply, a step after a tool step that
    # does not read it.
    catalog = _catalog(VALUES, DETAILS)

    spec = _compile_create(_two_tool_flow(), catalog, confirmed=(DEPARTMENT,))

    first, second, third = spec.steps
    assert (first.input_source, first.input_type) == (InputSource.TOOL, InputType.TEXT)
    assert first.input_config == {
        TOOL_INPUT_CONFIG_KEY: ToolInputConfig(
            mcp_server_id=SERVER,
            tool_id=VALUES_TOOL,
            arguments={
                "from_date": form_field_reference_expression("from_date"),
                "to_date": form_field_reference_expression("to_date"),
                "unit": "day",
            },
        ).model_dump(mode="json")
    }
    assert second.input_source is InputSource.TOOL
    assert second.input_config == {
        TOOL_INPUT_CONFIG_KEY: ToolInputConfig(
            mcp_server_id=SERVER,
            tool_id=DETAILS_TOOL,
            arguments={
                "days": SourceRefBinding(
                    step_ref=first.plan_step_ref,
                    output="structured",
                    field_path=("days",),
                ).template_expression()
            },
        ).model_dump(mode="json")
    }
    assert third.input_source is InputSource.PREVIOUS_STEP
    assert [
        (field.name, field.type, field.label, field.required)
        for field in spec.form_fields or ()
    ] == [
        ("department", "text", "Avdelning", False),
        ("from_date", "date", "Från datum", True),
        ("to_date", "date", "Till datum", True),
    ]
    applied = flow_step_validation_views_from_draft_spec(spec.steps)
    assert applied[1].input_config == {
        TOOL_INPUT_CONFIG_KEY: {
            "mcp_server_id": str(SERVER),
            "tool_id": str(DETAILS_TOOL),
            "arguments": {"days": "{{ step_1.output.structured.days }}"},
        }
    }
    prepared = _prepare(spec, catalog)
    assert prepared.answer is None and prepared.validation is not None
    assert (prepared.validation.errors, prepared.validation.warnings) == ([], [])


def test_an_argument_bound_to_a_field_the_earlier_step_lacks_is_repaired() -> None:
    # Kills: an earlier-step argument compiled without the declared-field
    # check every previous-field reference gets.
    with pytest.raises(AIBuilderArchitectureError) as raised:
        _compile_create(_two_tool_flow(days_path="weeks"), _catalog(VALUES, DETAILS))

    assert raised.value.repair_disposition == "model_correctable"
    assert "does not declare the field `weeks`" in raised.value.detail


def _dates(**from_date: Any) -> list[dict[str, Any]]:
    """The values tool's arguments: from_date as given, to_date fixed."""
    return [
        _argument("from_date", **from_date),
        _argument("to_date", "fixed", value_json='"2026-09-30"'),
    ]


@pytest.mark.parametrize(
    ("arguments", "context", "reason"),
    [
        pytest.param(
            _two_tool_flow(
                values_arguments=_dates(
                    source="fixed", value_json='"{{ flow_input.department }}"'
                )
            ),
            {},
            "tool_argument_fixed_reference",
            id="a-fixed-value-holds-a-reference",
        ),
        pytest.param(
            _two_tool_flow(),
            {"runtime_input_type": InputType.DOCUMENT},
            "tool_step_before_run_input",
            id="a-tool-first-flow-started-with-a-file",
        ),
        pytest.param(
            {
                **_two_tool_flow(),
                "steps": [
                    _step_payload("Skriv ut", None),
                    _two_tool_flow()["steps"][1],
                ],
            },
            {
                "runtime_input_type": InputType.AUDIO,
                "final_output_mode": OutputMode.TRANSCRIBE_ONLY,
            },
            "tool_step_shape_unsupported",
            id="an-audio-transcription-only-flow",
        ),
        pytest.param(
            _two_tool_flow(
                values_arguments=_dates(source="run_input", field_name="department")
            ),
            {},
            "tool_argument_run_input_type_mismatch",
            id="a-run-form-field-of-another-type",
        ),
        pytest.param(
            _two_tool_flow(
                values_arguments=_dates(source="run_input", field_name="Department")
            ),
            {},
            "tool_argument_run_input_field_name_case",
            id="a-run-form-field-named-in-another-case",
        ),
    ],
)
def test_a_create_tool_step_the_flow_cannot_take_is_repaired(
    arguments: dict[str, Any], context: dict[str, Any], reason: str
) -> None:
    # Kills: a fixed value read as a binding, a tool-first plan that drops
    # the file a run is started with, a tool step in a flow whose shape takes
    # none, a run-form field of another type bound to an argument, and an
    # existing field named in another case ending the turn as a server
    # defect (the binding must name the field as the form does).
    with pytest.raises(AIBuilderArchitectureError) as raised:
        _compile_create(
            arguments, _catalog(VALUES, DETAILS), confirmed=(DEPARTMENT,), **context
        )

    assert raised.value.repair_disposition == "model_correctable"
    assert raised.value.log_context["reason"] == reason


def test_an_earlier_step_argument_counts_the_steps_of_the_proposal() -> None:
    # Kills: from_step resolved against the compiled flow, where an audio
    # run's transcription step stands before the proposal's first step.
    flow = _two_tool_flow()
    flow["steps"][0] = _step_payload("Hitta dagar i samtalet", None, "days")
    spec = _compile_create(
        flow, _catalog(VALUES, DETAILS), runtime_input_type=InputType.AUDIO
    )

    transcription, first, details, _ = spec.steps
    assert transcription.input_source is InputSource.FLOW_INPUT
    assert details.input_config is not None
    assert details.input_config[TOOL_INPUT_CONFIG_KEY]["arguments"] == {
        "days": SourceRefBinding(
            step_ref=first.plan_step_ref, output="structured", field_path=("days",)
        ).template_expression()
    }


@pytest.mark.parametrize(
    ("value_json", "admitted"),
    [
        ("NaN", False),
        ("-Infinity", False),
        ("1e400", False),
        ("9007199254740993", False),
        ("9007199254740991", True),
        ("[1.5]", True),
    ],
)
def test_a_fixed_value_is_json_the_editor_holds_exactly(
    value_json: str, admitted: bool
) -> None:
    # Kills: a non-finite number, or an integer past the editor's exact range,
    # reaching the turn as a value (it crashed the argument check).
    intent = {
        "use_ref": "u",
        "tool_ref": VALUES_REF,
        "arguments": [_argument("unit", "fixed", value_json=value_json)],
    }
    if admitted:
        ToolUseIntent.model_validate(intent)
        return
    with pytest.raises(ValidationError, match="value_json must be one JSON value"):
        ToolUseIntent.model_validate(intent)


def test_a_ref_the_space_has_no_tool_for_is_repaired_and_a_refused_one_answered() -> (
    None
):
    # Kills: a guessed tool for an unknown ref, a refused tool compiled into a
    # step, a refusal answered without its reason.
    catalog = _catalog(VALUES, OFF).tools

    unknown = tool_use_ref_outcome(
        [("step 1", ToolUseIntent(use_ref="u", tool_ref="tool_ffffffff"))],
        catalog=catalog,
        ui_language="en",
    )
    refused = tool_use_ref_outcome(
        [
            ("step 1", ToolUseIntent(use_ref="u", tool_ref=VALUES_REF)),
            ("step 2", ToolUseIntent(use_ref="u", tool_ref=OFF_REF)),
        ],
        catalog=catalog,
        ui_language="sv",
    )

    assert isinstance(unknown, CorrectableFailure)
    assert "tool_ffffffff" in unknown.feedback and VALUES_REF in unknown.feedback
    assert isinstance(refused, ProposalAnswer) and refused.outcome is not None
    assert refused.outcome.kind == "tool_not_usable"
    assert refused.codes == frozenset({"tool_switched_off_in_space"})
    assert "`archive`" in refused.answer and "avstängt i den här ytan" in refused.answer


def test_every_refusal_is_answered_in_both_languages() -> None:
    # Kills: a refusal the chain gains without a Swedish or an English
    # sentence, which would end the turn as a server error.
    for reason in UnattendedToolRefusal:
        catalog = _catalog(_option(OFF_TOOL, "archive", None, refusal=reason)).tools
        for language in ("sv", "en"):
            answer = tool_use_ref_outcome(
                [("step 1", ToolUseIntent(use_ref="u", tool_ref=OFF_REF))],
                catalog=catalog,
                ui_language=language,
            )
            assert isinstance(answer, ProposalAnswer)
            assert answer.codes == frozenset({reason.value})


def _values_spec(arguments: dict[str, object]) -> FlowDraftSpecCore:
    """A create spec whose one tool step gives the values tool `arguments`."""
    spec = _compile_create(
        _two_tool_flow(
            values_arguments=[
                _argument("from_date", "fixed", value_json='"2026-09-01"'),
                _argument("to_date", "fixed", value_json='"2026-09-30"'),
            ]
        ),
        _catalog(VALUES, DETAILS),
    )
    config = {
        TOOL_INPUT_CONFIG_KEY: {
            "mcp_server_id": str(SERVER),
            "tool_id": str(VALUES_TOOL),
            "arguments": arguments,
        }
    }
    return spec.model_copy(
        update={
            "steps": [
                spec.steps[0].model_copy(update={"input_config": config}),
                *spec.steps[1:],
            ]
        }
    )


@pytest.mark.parametrize(
    ("arguments", "code", "named"),
    [
        (
            {"from_date": "2026-09-01"},
            "tool_argument_missing_required",
            'The argument\'s schema: {"format":"date","type":"string"}',
        ),
        (
            {"from_date": "2026-09-01", "to_date": "2026-09-30", "unit": "week"},
            "tool_argument_outside_schema",
            'The argument\'s schema: {"enum":["hour","day"],"type":"string"}',
        ),
        (
            {"from_date": "2026-09-01", "to_date": "2026-09-30", "limit": 10},
            "tool_argument_undeclared_argument",
            "from_date, to_date, unit",
        ),
    ],
    ids=["missing_required", "outside_schema", "undeclared_argument"],
)
def test_an_argument_the_tool_refuses_is_an_error_the_model_repairs(
    arguments: dict[str, object], code: str, named: str
) -> None:
    # Kills: the final spec not checked with publish's checks, a refused
    # argument let through, a repair that does not name the argument and
    # what the schema takes for it.
    prepared = _prepare(_values_spec(arguments), _catalog(VALUES, DETAILS))

    assert prepared.answer is None and prepared.validation is not None
    assert [error.code for error in prepared.validation.errors] == [code]
    assert "values_by_day" in prepared.validation.errors[0].message
    assert named in prepared.validation.errors[0].message


def test_a_schema_no_flow_can_check_is_answered_and_a_failed_checker_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Kills: an invalid schema sent to repair (the model cannot change it),
    # a checker host fault turned into an error or swallowed silently.
    invalid = _option(VALUES_TOOL, "values_by_day", {"type": 12})
    answered = _prepare(_values_spec({}), _catalog(invalid, DETAILS))

    async def host_fault(*_: object) -> object:
        raise tool_argument_check.ToolArgumentCheckFailed()

    monkeypatch.setattr(
        "eneo.flows.application.flow_tool_publication.check_fixed_tool_properties",
        host_fault,
    )
    warned = _prepare(
        _values_spec({"from_date": "2026-09-01", "to_date": "2026-09-30"}),
        _catalog(VALUES, DETAILS),
    )

    assert isinstance(answered.answer, ProposalAnswer)
    assert answered.answer.codes == frozenset({"tool_input_schema_invalid"})
    assert warned.answer is None and warned.validation is not None
    assert warned.validation.errors == []
    assert [w.code for w in warned.validation.warnings] == ["tool_argument_unverified"]


@pytest.mark.parametrize(
    ("schema", "shape"),
    [
        ({"type": "string", "format": "date"}, RunFormFieldShape("date")),
        ({"type": "integer"}, RunFormFieldShape("number")),
        ({"type": "number"}, RunFormFieldShape("number")),
        ({"type": "string"}, RunFormFieldShape("text")),
        ({"enum": ["a", "b"]}, RunFormFieldShape("select", ("a", "b"))),
        (
            {"type": "array", "items": {"enum": ["a", "b"]}},
            RunFormFieldShape("multiselect", ("a", "b")),
        ),
        ({"type": "array", "items": {"type": "string"}}, RunFormFieldShape("list")),
        ({"type": "object"}, None),
        ({"enum": ["a", ""]}, None),
        ({"enum": ["a", "A"]}, None),
        ({"enum": [" a"]}, None),
        ({"type": "array", "items": {"type": "string", "enum": [" a"]}}, None),
        ({"type": "array", "items": {"type": "integer", "enum": [1, 2]}}, None),
        ({"type": "array", "enum": [["a"]], "items": {"type": "string"}}, None),
        ({"type": "integer", "enum": [1, 2]}, None),
        ({"type": "string", "enum": [1, "a"]}, None),
        ({"type": "integer", "enum": ["a", "b"]}, None),
        ({"anyOf": [{"type": "string"}]}, None),
        ({"type": "array", "items": {"type": "integer"}}, None),
    ],
)
def test_an_argument_asked_at_run_time_gets_the_field_type_its_schema_accepts(
    schema: dict[str, object], shape: RunFormFieldShape | None
) -> None:
    # Kills: any row of the mapping changed, a field offered for a schema no
    # field type fills, a select whose options the run form refuses or
    # changes (blank, repeated in another case, padded), and a present enum
    # the form cannot hold read as the plain text, number or list field of
    # its type (which accepts values the enum refuses or changes them).
    assert tool_argument_form_field(schema) == shape


CHOICE_TOOL_A = UUID("a1b2c3d4-0000-4a6b-8c7d-9e0f1a2b3c01")
CHOICE_TOOL_B = UUID("a1b2c3d4-0000-4a6b-8c7d-9e0f1a2b3c02")


def _choice_tool(
    tool_id: UUID, name: str, properties: dict[str, object], *required: str
) -> FlowToolOption:
    return _option(
        tool_id,
        name,
        {"type": "object", "properties": properties, "required": list(required)},
    )


def _run_input_flow(*uses: tuple[FlowToolOption, dict[str, str]]) -> dict[str, Any]:
    """One tool step per use, each argument asked at run time under the field
    name given, then a writing step."""
    return {
        "flow_name": "Val",
        "plan_rationale": "Läs verktyg, skriv.",
        "steps": [
            *(
                _step_payload(
                    f"Steg {index}",
                    {
                        "use_ref": f"use{index}",
                        "tool_ref": tool_ref(SERVER, tool.tool_id),
                        "alternative_refs": [],
                        "evidence_quote": None,
                        "arguments": [
                            _argument(
                                argument,
                                "run_input",
                                field_name=field,
                                field_label=field,
                            )
                            for argument, field in fields.items()
                        ],
                    },
                )
                for index, (tool, fields) in enumerate(uses, start=1)
            ),
            _step_payload("Skriv", None),
        ],
    }


def _form_of(
    flow: dict[str, Any], *tools: FlowToolOption, confirmed: tuple[Any, ...] = ()
) -> list[tuple[str, str, bool, list[str] | None]]:
    spec = _compile_create(flow, _catalog(*tools), confirmed=confirmed)
    return [
        (field.name, field.type, field.required, field.options)
        for field in spec.form_fields or ()
    ]


def _enum_tool(tool_id: UUID, name: str, *values: str) -> FlowToolOption:
    return _choice_tool(
        tool_id, name, {"pick": {"type": "string", "enum": list(values)}}, "pick"
    )


def test_a_field_two_tools_share_must_take_every_value_each_of_them_accepts() -> None:
    # Kills: a run-form field reused for a second tool by its type alone
    # (select options ["a"] compiled for a tool that accepts only "b", which
    # fails at run time), and a compatible reuse refused (same options, or a
    # field that offers fewer values than the tool accepts).
    wide = _enum_tool(CHOICE_TOOL_B, "wide", "a", "b")
    narrow = _enum_tool(CHOICE_TOOL_A, "narrow", "a")
    other = _enum_tool(OFF_TOOL, "other", "b")
    same = {"pick": "val"}

    assert _form_of(_run_input_flow((narrow, same), (wide, same)), narrow, wide) == [
        ("val", "select", True, ["a"])
    ]
    with pytest.raises(AIBuilderArchitectureError) as raised:
        _form_of(_run_input_flow((narrow, same), (other, same)), narrow, other)
    assert raised.value.repair_disposition == "model_correctable"
    assert (
        raised.value.log_context["reason"] == "tool_argument_run_input_options_mismatch"
    )
    with pytest.raises(AIBuilderArchitectureError) as raised:
        _form_of(_run_input_flow((wide, same), (narrow, same)), wide, narrow)
    assert (
        raised.value.log_context["reason"] == "tool_argument_run_input_options_mismatch"
    )


def test_a_created_field_is_required_when_any_tool_that_reads_it_requires_it() -> None:
    # Kills: requiredness taken from the first argument that creates the
    # field (an optional argument first leaves a field that sends the next
    # tool's required argument empty), and an optional use weakening a
    # required field.
    both = _choice_tool(
        CHOICE_TOOL_A,
        "both",
        {"first": {"type": "integer"}, "second": {"type": "integer"}},
        "second",
    )
    swapped = _choice_tool(
        CHOICE_TOOL_B,
        "swapped",
        {"first": {"type": "integer"}, "second": {"type": "integer"}},
        "first",
    )
    one_field = {"first": "count", "second": "count"}

    assert _form_of(_run_input_flow((both, one_field)), both) == [
        ("count", "number", True, None)
    ]
    assert _form_of(_run_input_flow((swapped, one_field)), swapped) == [
        ("count", "number", True, None)
    ]


def test_a_required_argument_is_not_bound_to_an_optional_saved_field() -> None:
    # Kills: a saved optional field bound to a required argument (a run that
    # leaves it empty sends the tool no value), and the conflict asked of the
    # model as a server defect.
    needs_department = _choice_tool(
        CHOICE_TOOL_A,
        "needs_department",
        {"department": {"type": "string"}},
        "department",
    )
    with pytest.raises(AIBuilderArchitectureError) as raised:
        _form_of(
            _run_input_flow((needs_department, {"department": "department"})),
            needs_department,
            confirmed=(DEPARTMENT,),
        )

    assert raised.value.repair_disposition == "model_correctable"
    assert (
        raised.value.log_context["reason"]
        == "tool_argument_run_input_required_mismatch"
    )


@pytest.mark.parametrize(
    ("purposes", "then_write", "query_in_questions"),
    [
        # Kills: the tool argument's exception dropped (a tool-only plan refused).
        ({"query": "interpret_input"}, False, []),
        # Kills: the exception taken although a step can take the field.
        ({"query": "interpret_input"}, True, [True]),
        # Kills: the exception for a field no tool argument reads.
        ({"query": "interpret_input", "audience": "interpret_input"}, False, None),
        # Kills: the exception moved before the purpose match (shaping the
        # result would then need no step).
        ({"query": "shape_result"}, False, None),
    ],
)
def test_a_tool_argument_reads_an_interpret_input_field_no_step_can_take(
    purposes: dict[str, RuntimeMetadataFieldPurpose],
    then_write: bool,
    query_in_questions: list[bool] | None,
) -> None:
    search = _choice_tool(
        CHOICE_TOOL_A, "search", {"query": {"type": "string"}}, "query"
    )
    flow = _run_input_flow((search, {"query": "query"}))
    if not then_write:
        flow["steps"].pop()
    value = DEPARTMENT.value.model_copy(update={"required": True})
    confirmed = tuple(
        DEPARTMENT.model_copy(
            update={
                "purpose": purpose,
                "value": value.model_copy(update={"variable_name": name}),
            }
        )
        for name, purpose in purposes.items()
    )
    if query_in_questions is None:
        with pytest.raises(AIBuilderArchitectureError) as raised:
            _compile_create(flow, _catalog(search), confirmed=confirmed)
        reason = raised.value.log_context["reason"]
        assert reason == "form_field_required_semantic_target_missing"
        return
    spec = _compile_create(flow, _catalog(search), confirmed=confirmed)
    assert [
        "{{ flow_input.query }}"
        in (effective_question_binding(step.input_bindings) or "")
        for step in spec.steps[1:]
    ] == query_in_questions


def _saved_flow() -> Flow:
    """Step 1 reads the values tool, step 2 the details tool for step 1's
    days, step 3 writes."""
    return _flow(
        _step(
            1,
            input_source="tool",
            input_type="text",
            output_type="json",
            output_contract={
                "type": "object",
                "properties": {"days": {"type": "array", "items": {"type": "string"}}},
                "required": ["days"],
            },
            input_config={
                "tool": {
                    "mcp_server_id": str(SERVER),
                    "tool_id": str(VALUES_TOOL),
                    "arguments": {"from_date": "2026-09-01", "to_date": "2026-09-30"},
                }
            },
        ),
        _step(
            2,
            input_source="tool",
            input_type="text",
            input_config={
                "tool": {
                    "mcp_server_id": str(SERVER),
                    "tool_id": str(DETAILS_TOOL),
                    "arguments": {"days": "{{step_1.output.structured.days}}"},
                }
            },
        ),
        _step(3),
    )


def _edit(
    flow: Flow,
    *steps: ModifyExistingStep | AddStep,
    removed: frozenset[str] = frozenset(),
    instructions: dict[int, str] | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> tuple[list[Any], Any]:
    """The edit as the Builder prepares it: each step as the apply writes it,
    and the validation. A saved step's instructions are ``Gör <order>.``
    unless ``instructions`` gives them."""
    catalog = _catalog(VALUES, DETAILS)
    compiled = compile_edit_proposal(
        OrderedEditProposal(
            plan_rationale="Edit.",
            steps=list(steps),
            removed_existing_step_refs=removed,
        ),
        flow.steps,
        base_flow_revision=1,
        flow_name=flow.name,
        current_metadata_json=metadata_json,
        assistant_snapshots={
            step.assistant_id: AssistantAuthoringSnapshot(
                instructions=(instructions or {}).get(
                    step.step_order, f"Gör {step.step_order}."
                )
            )
            for step in flow.steps
        },
        resource_catalog=catalog,
    )
    prepared = _prepare(
        compiled.spec,
        catalog,
        target_kind=TargetKind.EDIT,
        mutation_scope=compiled.mutation_scope,
    )
    assert prepared.spec is not None and prepared.validation is not None
    modified = {
        change.step_ref: frozenset(field.field for field in change.field_changes)
        for change in compiled.approval_for_prepared_spec(
            prepared.spec
        ).diff.step_changes
        if change.kind == "modified" and change.step_ref
    }
    # The apply writes the columns the approved diff names.
    changeset = compile_flow_draft_changeset(
        prepared.spec,
        flow,
        removed_existing_step_refs=removed,
        updated_existing_step_refs=frozenset(modified),
        updated_step_fields={
            ref: ALL_STEP_COLUMNS & fields for ref, fields in modified.items()
        },
    )
    return changeset.compiled_steps, prepared.validation


def test_an_edit_adds_a_tool_step_and_keeps_the_saved_ones() -> None:
    # Kills: a saved tool step re-compiled because the turn wrote another
    # tool use (kept refs emptied), an added tool step given the run's
    # primary input.
    flow = _saved_flow()
    steps, validation = _edit(
        flow,
        ModifyExistingStep(existing_step_ref="existing_step_1"),
        ModifyExistingStep(existing_step_ref="existing_step_2"),
        AddStep(
            step=SemanticStepIntent(
                name="Fler detaljer",
                instructions="Hämta detaljer igen.",
                tool_use=ToolUseIntent.model_validate(
                    {
                        "use_ref": "u",
                        "tool_ref": DETAILS_REF,
                        "arguments": [
                            _argument(
                                "days", "earlier_step", from_step=1, field_path="days"
                            )
                        ],
                    }
                ),
            )
        ),
        ModifyExistingStep(existing_step_ref="existing_step_3"),
    )

    assert validation.errors == []
    assert [step.input_config for step in steps[:2]] == [
        step.input_config for step in flow.steps[:2]
    ]
    assert steps[2].input_config == {
        TOOL_INPUT_CONFIG_KEY: {
            "mcp_server_id": str(SERVER),
            "tool_id": str(DETAILS_TOOL),
            "arguments": {"days": "{{ step_1.output.structured.days }}"},
        }
    }


_DATES = _dates(source="fixed", value_json='"2026-09-01"')
_ASK = "Ansökan:\n{{ flow_input.ansokan }}"
_FORM = _form_metadata(variable_name="ansokan", label="Ansökan")


def _insert_before(first_step: FlowStep, **edit: Any) -> tuple[list[Any], Any]:
    """An edit that inserts a values tool step before the saved first step
    (`first_step`, then a saved step 2) and keeps both saved steps."""
    return _edit(
        _flow(first_step, _step(2)),
        AddStep(
            step=SemanticStepIntent(
                name="Hämta värden",
                instructions="Hämta värden.",
                tool_use=ToolUseIntent.model_validate(
                    {"use_ref": "u", "tool_ref": VALUES_REF, "arguments": _DATES}
                ),
            )
        ),
        ModifyExistingStep(existing_step_ref="existing_step_1"),
        ModifyExistingStep(existing_step_ref="existing_step_2"),
        **edit,
    )


def _upload(input_format: str) -> dict[str, Any]:
    return {
        "runtime_input": {
            "enabled": True,
            "required": True,
            "input_format": input_format,
        }
    }


@pytest.mark.parametrize(
    ("metadata_json", "first_step", "input_source"),
    [
        # Kills: the displaced step left on flow_input at position 2
        # (flow_input_not_first, which the model cannot repair), and a rebase
        # that rewrites its bindings.
        (
            _FORM,
            _step(1, input_type="text", input_bindings={"question": _ASK}),
            "previous_step",
        ),
        # Kills: a step that names the run's text refused; an explicit
        # reference never reads input_source.
        (
            None,
            _step(
                1,
                input_type="text",
                input_bindings={"question": "{{ flow_input.text }}"},
            ),
            "previous_step",
        ),
    ],
    ids=["form_field", "run_text"],
)
def test_a_saved_first_step_that_names_what_it_reads_follows_an_inserted_step(
    metadata_json: dict[str, Any] | None, first_step: FlowStep, input_source: str
) -> None:
    steps, validation = _insert_before(first_step, metadata_json=metadata_json)

    assert validation.errors == []
    assert steps[1].input_source.value == input_source
    assert steps[1].input_bindings == first_step.input_bindings


@pytest.mark.parametrize(
    "first_step",
    [
        # Kills: the implicit read of the run input not counted.
        _step(1, input_type="text"),
        # Kills: an upload not counted at all.
        _step(
            1,
            input_type="audio",
            output_mode="transcribe_only",
            input_config=_upload("audio"),
        ),
        # Kills: the runtime upload the apply gives a document step not counted.
        _step(1, input_bindings={"question": _ASK}),
        # Kills: a {{ step_input }} read not counted.
        _step(
            1,
            input_type="text",
            input_bindings={"question": "{{ step_input.text }}"},
            input_config=_upload("document"),
        ),
        # Kills: a configuration that cannot be read counted as reading nothing.
        _step(
            1,
            input_type="text",
            input_bindings={"question": _ASK},
            output_mode="template_fill",
            output_type="docx",
            output_config={"bindings": "x"},
        ),
    ],
    ids=["implicit", "audio_upload", "document", "step_input", "unreadable_config"],
)
def test_a_saved_first_step_that_takes_the_run_input_by_position_stays_first(
    first_step: FlowStep,
) -> None:
    with pytest.raises(AIBuilderArchitectureError) as raised:
        _insert_before(first_step, metadata_json=_FORM)

    assert raised.value.repair_disposition == "model_correctable"
    assert raised.value.log_context["reason"] == "run_input_step_displaced"
    assert "Steg 1" in raised.value.detail


def test_an_edit_checks_the_tool_steps_it_writes_and_not_the_saved_ones() -> None:
    # Kills: the tool steps an edit adds left unchecked, a saved tool step
    # the edit keeps sent to repair for what it was published with.
    saved = _saved_flow()
    first = saved.steps[0]
    flow = _flow(
        first.model_copy(
            update={
                "input_config": {
                    "tool": {
                        "mcp_server_id": str(SERVER),
                        "tool_id": str(VALUES_TOOL),
                        "arguments": {"from_date": "2026-09-01"},
                    }
                }
            }
        ),
        *saved.steps[1:],
    )
    _, validation = _edit(
        flow,
        *(
            ModifyExistingStep(existing_step_ref=f"existing_step_{order}")
            for order in (1, 2, 3)
        ),
        AddStep(
            step=SemanticStepIntent(
                name="Fler värden",
                instructions="Hämta värden.",
                tool_use=ToolUseIntent.model_validate(
                    {
                        "use_ref": "u",
                        "tool_ref": VALUES_REF,
                        "arguments": [
                            _argument("from_date", "fixed", value_json='"2026-10-01"')
                        ],
                    }
                ),
            )
        ),
    )

    assert [(error.step_ref, error.code) for error in validation.errors] == [
        ("step_d", "tool_argument_missing_required")
    ]


def test_an_edit_changes_a_tool_steps_arguments_and_nothing_else_of_it() -> None:
    # Kills: a tool use written onto a step that reads no tool, a change of
    # a tool step's name let through with its tool use, the other tool step
    # unguarded once one tool use is written.
    flow = _saved_flow()
    new_dates = ToolUseIntent.model_validate(
        {
            "use_ref": "u",
            "tool_ref": VALUES_REF,
            "arguments": [
                _argument("from_date", "fixed", value_json='"2026-10-01"'),
                _argument("to_date", "fixed", value_json='"2026-10-31"'),
            ],
        }
    )
    keep_rest = [
        ModifyExistingStep(existing_step_ref="existing_step_2"),
        ModifyExistingStep(existing_step_ref="existing_step_3"),
    ]

    steps, validation = _edit(
        flow,
        ModifyExistingStep(existing_step_ref="existing_step_1", tool_use=new_dates),
        *keep_rest,
    )
    with pytest.raises(AIBuilderBadRequestException, match="changes only their"):
        _edit(
            flow,
            ModifyExistingStep(
                existing_step_ref="existing_step_1", tool_use=new_dates, name="Nytt"
            ),
            *keep_rest,
        )
    with pytest.raises(AIBuilderBadRequestException, match="read no MCP tool"):
        _edit(
            flow,
            ModifyExistingStep(existing_step_ref="existing_step_1"),
            ModifyExistingStep(existing_step_ref="existing_step_2"),
            ModifyExistingStep(existing_step_ref="existing_step_3", tool_use=new_dates),
        )

    assert validation.errors == []
    assert [step.input_config for step in steps] == [
        {
            TOOL_INPUT_CONFIG_KEY: {
                "mcp_server_id": str(SERVER),
                "tool_id": str(VALUES_TOOL),
                "arguments": {"from_date": "2026-10-01", "to_date": "2026-10-31"},
            }
        },
        flow.steps[1].input_config,
        flow.steps[2].input_config,
    ]


@pytest.mark.parametrize(
    ("writes_its_tool_use", "instructions", "retargeted"),
    [
        pytest.param(False, "Gör 5.", 2, id="kept"),
        pytest.param(True, "Jämför svaret med {{Original}}.", 2, id="written"),
        pytest.param(True, "Gör 5.", 1, id="written-arguments-are-the-edits"),
    ],
)
def test_a_tool_steps_reads_keep_their_producer_unless_the_edit_writes_them(
    writes_its_tool_use: bool, instructions: str, retargeted: int
) -> None:
    # Kills: a saved tool step left unguarded once the edit writes a tool use
    # (kept), or once the edit writes its own tool use (written): its
    # argument, or its instructions, would then silently read the step that
    # took its producer's name; and the saved arguments of a step whose tool
    # use the edit writes judged, though the edit replaces them.
    flow = _flow(
        _step(1),
        _step(2, user_description="Original", input_type="text"),
        _step(3, user_description="Other", input_type="text"),
        _step(
            4,
            input_source="tool",
            input_type="text",
            input_config={
                "tool": {
                    "mcp_server_id": str(SERVER),
                    "tool_id": str(VALUES_TOOL),
                    "arguments": {"from_date": "{{Original}}", "to_date": "x"},
                }
            },
        ),
        _step(
            5,
            input_source="tool",
            input_type="text",
            input_config={
                "tool": {
                    "mcp_server_id": str(SERVER),
                    "tool_id": str(DETAILS_TOOL),
                    "arguments": {"days": "{{Original}}"},
                }
            },
        ),
    )
    days = ToolUseIntent.model_validate(
        {
            "use_ref": "days",
            "tool_ref": DETAILS_REF,
            "arguments": [_argument("days", "fixed", value_json='["2026-10-01"]')],
        }
    )
    _, validation = _edit(
        flow,
        ModifyExistingStep(existing_step_ref="existing_step_1"),
        ModifyExistingStep(existing_step_ref="existing_step_3", name="Original"),
        ModifyExistingStep(existing_step_ref="existing_step_4"),
        ModifyExistingStep(
            existing_step_ref="existing_step_5",
            tool_use=days if writes_its_tool_use else None,
        ),
        removed=frozenset({"existing_step_2"}),
        instructions={5: instructions},
    )

    assert [error.code for error in validation.errors] == [
        "kept_step_read_retargeted"
    ] * retargeted


def test_an_edit_binds_a_tool_argument_only_to_a_field_its_run_form_keeps() -> None:
    # Kills: an edit's run_input argument bound to a run-form field the flow
    # does not have.
    with pytest.raises(AIBuilderArchitectureError) as raised:
        _edit(
            _saved_flow(),
            ModifyExistingStep(
                existing_step_ref="existing_step_1",
                tool_use=ToolUseIntent.model_validate(
                    {
                        "use_ref": "u",
                        "tool_ref": VALUES_REF,
                        "arguments": _dates(source="run_input", field_name="from_date"),
                    }
                ),
            ),
            ModifyExistingStep(existing_step_ref="existing_step_2"),
            ModifyExistingStep(existing_step_ref="existing_step_3"),
        )

    assert raised.value.repair_disposition == "model_correctable"
    assert raised.value.log_context["reason"] == "tool_argument_run_input_field_missing"


@pytest.mark.parametrize("fit_lists_tools", [True, False], ids=["listed", "fitted-out"])
def test_a_turn_on_a_tool_step_is_served_when_its_prompt_names_tools(
    monkeypatch: pytest.MonkeyPatch, fit_lists_tools: bool
) -> None:
    # Kills: a scoped turn on a tool step refused although the turn can
    # write its tool use, a scoped schema offering the step more than its
    # tool use, and one whose prompt fit left out every tool paid for with
    # a schema no answer fits (no tool to name, the step still required).
    if not fit_lists_tools:
        monkeypatch.setattr(
            ai_builder_planner_request_preparation,
            "fit_tool_catalog_projection",
            lambda projection, fits: AIBuilderToolCatalogTooLarge(),
        )
    flow = _saved_flow()

    def prepare() -> ProposalPrepared:
        return build_proposal_prepared(
            requirements_state=RequirementsState(),
            ui_language="en",
            slot_classification_metadata=None,
            conversation=[ConversationMessage(role="user", content="Ta oktober.")],
            planning_state=PlanningState.empty(),
            attachment_context=None,
            flow_context=None,
            is_edit_mode=True,
            resource_catalog=_catalog(VALUES, DETAILS),
            flow=flow,
            assistant_snapshots=None,
            plan_edit_context=_scoped_to(flow.steps[0]),
            prior_plan_for_revision=None,
            litellm_model="gpt-4o-mini",
            capacity=ModelCapacity(100_000, 1024),
            budget_policy=_budget_policy(),
            attachment_file_count=0,
            current_turn_start=0,
        )

    if not fit_lists_tools:
        with pytest.raises(UnsupportedSavedStepsError):
            prepare()
        return
    prepared = prepare()
    steps = prepared.proposal_tool_schema["function"]["parameters"]["properties"][
        "steps"
    ]
    assert steps["maxItems"] == 1
    assert set(steps["items"]["properties"]) == {
        "kind",
        "existing_step_ref",
        "tool_use",
    }
    assert steps["items"]["properties"]["existing_step_ref"]["enum"] == [
        "existing_step_1"
    ]
