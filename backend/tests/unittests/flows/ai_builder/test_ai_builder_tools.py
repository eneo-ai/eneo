"""Tests for active AI Builder tool schemas and parsing helpers."""

from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.flows.ai_builder import ai_builder_tool_names, ai_builder_tools
from eneo.flows.ai_builder.ai_builder_edit_tool_schema import (
    build_edit_flow_tool_schema,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    ProposalIntentArgumentError,
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_runtime_input_requirements import (
    ConfirmedRuntimeInputRequirement,
    render_confirmed_runtime_input_requirements,
)
from eneo.flows.ai_builder.ai_builder_tool_parsing import (
    ToolArgumentParseError,
    parse_tool_call_arguments,
)
from eneo.flows.ai_builder.ai_builder_tools import (
    PROPOSE_FLOW_TOOL_NAME,
    ProposalToolArgumentsError,
    admit_propose_flow_tool_arguments,
    build_propose_flow_tool_schema,
    extract_assumptions,
    extract_plan_rationale,
    validate_propose_flow_tool_arguments,
)
from eneo.flows.domain.flow import FlowStep


def _empty_catalog() -> AIBuilderResourceCatalog:
    return build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
    )


class TestBuildToolSchema:
    def test_single_active_submission_tool_name_is_canonical(self) -> None:
        assert PROPOSE_FLOW_TOOL_NAME == "propose_flow"
        assert "PROPOSE_FLOW_TOOL_NAME" in ai_builder_tool_names.__all__
        assert "PROPOSE_FLOW_TOOL_NAME" not in ai_builder_tools.__all__
        assert "ASK_STRUCTURED_QUESTION_TOOL_NAME" not in ai_builder_tools.__all__
        assert "CONFIRM_REQUIREMENTS_TOOL_NAME" not in ai_builder_tools.__all__
        assert "active_submission_tool_name" not in ai_builder_tools.__all__
        assert "ActiveSubmissionToolName" not in ai_builder_tools.__all__
        assert "OUTLINE_FLOW_TOOL_NAME" not in ai_builder_tools.__all__
        assert "EDIT_FLOW_TOOL_NAME" not in ai_builder_tools.__all__
        assert not hasattr(ai_builder_tools, "ASK_STRUCTURED_QUESTION_TOOL_NAME")
        assert not hasattr(ai_builder_tools, "CONFIRM_REQUIREMENTS_TOOL_NAME")
        assert not hasattr(ai_builder_tools, "VALIDATE_FLOW_DRAFT_TOOL_NAME")
        assert not hasattr(ai_builder_tools, "OUTLINE_FLOW_TOOL_NAME")
        assert not hasattr(ai_builder_tools, "EDIT_FLOW_TOOL_NAME")
        assert not hasattr(ai_builder_tools, "active_submission_tool_name")

    def test_obsolete_question_and_confirm_tool_schemas_are_not_exported(self) -> None:
        assert not hasattr(ai_builder_tools, "build_all_tool_schemas")
        assert not hasattr(
            ai_builder_tools, "build_ask_structured_question_tool_schema"
        )
        assert not hasattr(ai_builder_tools, "build_confirm_requirements_tool_schema")
        assert not hasattr(ai_builder_tools, "build_discovery_complete_tool_schemas")
        assert not hasattr(ai_builder_tools, "build_free_discovery_tool_schemas")
        assert not hasattr(ai_builder_tools, "build_validate_flow_draft_tool_schema")
        assert not hasattr(ai_builder_tools, "parse_propose_flow_arguments")

    def test_retired_persisted_tool_names_are_byte_locked(self) -> None:
        assert (
            ai_builder_tool_names.ASK_STRUCTURED_QUESTION_TOOL_NAME
            == "ask_structured_question"
        )

    def test_outline_schema_hides_backend_owned_mechanics(self) -> None:
        schema = build_propose_flow_tool_schema(resource_catalog=_empty_catalog())
        assert schema["function"]["name"] == PROPOSE_FLOW_TOOL_NAME

        properties = schema["function"]["parameters"]["properties"]
        step_properties = properties["steps"]["items"]["properties"]

        assert "input_source" not in step_properties
        assert "input_type" not in step_properties
        assert "input_bindings" not in step_properties
        assert "output_type" not in step_properties
        assert "output_mode" not in step_properties
        assert "review_mode" not in step_properties
        assert "uses_form_fields" not in step_properties
        assert "uses_previous_fields" not in step_properties
        assert "uses_previous_outputs" not in step_properties
        assert "plan_step_ref" not in step_properties
        assert "runtime_input" not in properties
        assert "final_output_type" not in properties
        assert "input_fields" not in properties

    def test_create_schema_requires_only_semantic_inputs_without_defaults(self) -> None:
        schema = build_propose_flow_tool_schema(resource_catalog=_empty_catalog())
        parameters = schema["function"]["parameters"]
        step_schema = parameters["properties"]["steps"]["items"]

        assert parameters["additionalProperties"] is False
        assert set(parameters["required"]) == {"flow_name", "plan_rationale", "steps"}
        assert step_schema["additionalProperties"] is False
        assert set(step_schema["required"]) == {"name", "instructions"}

        arguments = {
            "flow_name": "Case assessment",
            "plan_rationale": "Assess the submitted case.",
            "steps": [
                {
                    "name": "Assess case",
                    "instructions": "Assess the submitted case material.",
                }
            ],
        }
        validate_propose_flow_tool_arguments(arguments=arguments, tool_schema=schema)
        intent = parse_create_flow_intent_arguments(arguments)
        assert intent.flow_description is None
        assert intent.assumptions == []
        assert intent.steps[0].output_fields is None
        assert intent.steps[0].model_ref is None
        assert intent.steps[0].knowledge_refs == []
        assert intent.steps[0].citations_requested is False

    def test_create_admission_does_not_invent_missing_step_instructions(self) -> None:
        schema = build_propose_flow_tool_schema(resource_catalog=_empty_catalog())
        arguments = {
            "flow_name": "Case assessment",
            "plan_rationale": "Assess the submitted case.",
            "steps": [{"name": "Assess case"}],
        }

        with pytest.raises(
            ProposalToolArgumentsError,
            match=r"steps\.0: 'instructions' is a required property",
        ):
            admit_propose_flow_tool_arguments(
                arguments=arguments,
                tool_schema=schema,
            )

    def test_create_admission_rehomes_unambiguous_step_tail_properties(self) -> None:
        schema = build_propose_flow_tool_schema(resource_catalog=_empty_catalog())
        arguments = {
            "flow_name": "Grounded assessment",
            "plan_rationale": "Assess the submitted material.",
            "steps": [
                {
                    "name": "Assess material",
                    "instructions": "Assess only the supplied material.",
                }
            ],
            "knowledge_refs": ["knowledge.policy"],
            "citations_requested": True,
        }

        admitted = admit_propose_flow_tool_arguments(
            arguments=arguments,
            tool_schema=schema,
        )

        assert "knowledge_refs" not in admitted
        assert "citations_requested" not in admitted
        assert admitted["steps"][-1]["knowledge_refs"] == ["knowledge.policy"]
        assert admitted["steps"][-1]["citations_requested"] is True
        assert "knowledge_refs" in arguments

    def test_create_admission_discards_identical_duplicate_step_tail(self) -> None:
        schema = build_propose_flow_tool_schema(resource_catalog=_empty_catalog())
        fields = [
            {
                "name": "summary",
                "field_type": "string",
                "description": "A concise summary.",
            }
        ]
        arguments = {
            "flow_name": "Grounded assessment",
            "plan_rationale": "Assess the submitted material.",
            "steps": [
                {
                    "name": "Assess material",
                    "instructions": "Assess only the supplied material.",
                    "model_ref": "model.default",
                    "output_fields": fields,
                }
            ],
            "model_ref": "model.default",
            "output_fields": fields,
        }

        admitted = admit_propose_flow_tool_arguments(
            arguments=arguments,
            tool_schema=schema,
        )

        assert "model_ref" not in admitted
        assert "output_fields" not in admitted
        assert admitted["steps"][-1]["model_ref"] == "model.default"
        assert admitted["steps"][-1]["output_fields"] == fields
        assert "model_ref" in arguments

    def test_create_schema_projects_runtime_identity_without_argument_shape_change(
        self,
    ) -> None:
        requirements = (
            ConfirmedRuntimeInputRequirement(
                name="audience", purpose="interpret_input"
            ),
            ConfirmedRuntimeInputRequirement(name="case_id", purpose="shape_result"),
            ConfirmedRuntimeInputRequirement(name="policy", purpose="whole_flow"),
        )
        rendered = render_confirmed_runtime_input_requirements(requirements)
        baseline = build_propose_flow_tool_schema(resource_catalog=_empty_catalog())
        contextual = build_propose_flow_tool_schema(
            resource_catalog=_empty_catalog(),
            confirmed_runtime_inputs=requirements,
        )

        baseline_parameters = baseline["function"]["parameters"]
        contextual_parameters = contextual["function"]["parameters"]
        baseline_step = baseline_parameters["properties"]["steps"]["items"]
        contextual_step = contextual_parameters["properties"]["steps"]["items"]
        assert set(contextual_parameters["properties"]) == set(
            baseline_parameters["properties"]
        )
        assert contextual_parameters["required"] == baseline_parameters["required"]
        assert set(contextual_step["properties"]) == set(baseline_step["properties"])
        assert contextual_step["required"] == baseline_step["required"]
        assert (
            contextual_step["properties"]["output_fields"]["items"]
            == baseline_step["properties"]["output_fields"]["items"]
        )
        description = contextual_step["properties"]["output_fields"]["description"]
        assert rendered in description

        baseline_edit = build_propose_flow_tool_schema(
            resource_catalog=_empty_catalog(), current_steps=[]
        )
        contextual_edit = build_propose_flow_tool_schema(
            resource_catalog=_empty_catalog(),
            current_steps=[],
            confirmed_runtime_inputs=requirements,
        )
        assert contextual_edit == baseline_edit

    def test_pure_audio_create_schema_accepts_exactly_one_semantic_step(self) -> None:
        schema = build_propose_flow_tool_schema(
            resource_catalog=_empty_catalog(),
            is_pure_audio_transcription=True,
        )
        parameters = schema["function"]["parameters"]
        steps_schema = parameters["properties"]["steps"]
        step_schema = steps_schema["items"]

        assert steps_schema["minItems"] == 1
        assert steps_schema["maxItems"] == 1
        assert step_schema["type"] == "object"
        assert step_schema["required"] == ["name", "instructions"]
        assert set(step_schema["properties"]) == {"name", "instructions"}
        assert step_schema["additionalProperties"] is False
        validate_propose_flow_tool_arguments(
            arguments={
                "flow_name": "Meeting transcript",
                "flow_description": None,
                "plan_rationale": "Return the transcript.",
                "steps": [
                    {
                        "name": "Transcribe meeting audio",
                        "instructions": "Transcribe the uploaded meeting audio.",
                    }
                ],
                "assumptions": [],
            },
            tool_schema=schema,
        )

        with pytest.raises(ProposalToolArgumentsError):
            validate_propose_flow_tool_arguments(
                arguments={
                    "flow_name": "Meeting transcript",
                    "flow_description": None,
                    "plan_rationale": "Return the transcript.",
                    "steps": [
                        {
                            "name": "Transcribe meeting audio",
                            "instructions": "Transcribe the uploaded meeting audio.",
                            "output_fields": None,
                        }
                    ],
                    "assumptions": [],
                },
                tool_schema=schema,
            )

    def test_create_structured_fields_use_one_closed_semantic_shape(self) -> None:
        schema = build_propose_flow_tool_schema(resource_catalog=_empty_catalog())
        step_schema = schema["function"]["parameters"]["properties"]["steps"]["items"]
        output_fields_schema = step_schema["properties"]["output_fields"]

        assert output_fields_schema["type"] == ["array", "null"]
        assert output_fields_schema["minItems"] == 1

        field_schema = output_fields_schema["items"]
        assert field_schema["type"] == "object"
        assert field_schema["required"] == ["name", "field_type", "description"]
        assert set(field_schema["properties"]) == {
            "name",
            "field_type",
            "description",
            "required",
            "children",
        }
        assert field_schema["additionalProperties"] is False
        assert "pattern" not in field_schema["properties"]["name"]
        assert field_schema["properties"]["required"]["default"] is True
        assert field_schema["properties"]["children"]["type"] == ["array", "null"]

        depth_four_schema = field_schema
        for _ in range(3):
            depth_four_schema = depth_four_schema["properties"]["children"]["items"]
        assert depth_four_schema["properties"]["field_type"]["enum"] == [
            "string",
            "number",
            "boolean",
            "array",
        ]
        assert depth_four_schema["properties"]["children"]["type"] == "null"

        assert list(step_schema["properties"])[-1] == "output_fields"
        assert list(schema["function"]["parameters"]["properties"])[-1] == "steps"

    def test_create_structured_field_defaults_are_admitted_by_the_wire_schema(
        self,
    ) -> None:
        schema = build_propose_flow_tool_schema(resource_catalog=_empty_catalog())
        arguments = {
            "flow_name": "Report",
            "plan_rationale": "Create the report.",
            "steps": [
                {
                    "name": "Write",
                    "instructions": "Write the report.",
                    "output_fields": [
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "A concise summary.",
                        }
                    ],
                }
            ],
        }

        validate_propose_flow_tool_arguments(arguments=arguments, tool_schema=schema)
        intent = parse_create_flow_intent_arguments(arguments)

        field = intent.steps[0].output_fields[0]
        assert field.required is True
        assert field.fields is None
        assert field.item_fields is None

    def test_create_object_without_members_is_admitted_as_open(self) -> None:
        schema = build_propose_flow_tool_schema(resource_catalog=_empty_catalog())
        arguments = {
            "flow_name": "Case statistics",
            "plan_rationale": "Summarize counts from the uploaded table.",
            "steps": [
                {
                    "name": "Calculate statistics",
                    "instructions": "Calculate counts by category.",
                    "output_fields": [
                        {
                            "name": "category_counts",
                            "field_type": "object",
                            "description": "Counts keyed by observed category.",
                        }
                    ],
                }
            ],
        }

        validate_propose_flow_tool_arguments(arguments=arguments, tool_schema=schema)
        intent = parse_create_flow_intent_arguments(arguments)

        field = intent.steps[0].output_fields[0]
        assert field.field_type == "object"
        assert field.fields is None
        assert field.allow_additional_properties is True

    def test_create_structured_field_relationships_are_owned_by_typed_admission(
        self,
    ) -> None:
        schema = build_propose_flow_tool_schema(resource_catalog=_empty_catalog())
        arguments = {
            "flow_name": "Report",
            "plan_rationale": "Create the report.",
            "steps": [
                {
                    "name": "Write",
                    "instructions": "Write the report.",
                    "output_fields": [
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "A concise summary.",
                            "children": [
                                {
                                    "name": "detail",
                                    "field_type": "string",
                                    "description": "A detail.",
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        validate_propose_flow_tool_arguments(arguments=arguments, tool_schema=schema)
        with pytest.raises(ProposalIntentArgumentError) as excinfo:
            parse_create_flow_intent_arguments(arguments)
        assert excinfo.value.issues == (
            "steps.0.output_fields.0: Value error, Only object or array fields may "
            "declare children ('summary'). [value_error]",
        )

    def test_create_schema_admits_explicit_empty_lists_and_nullable_scalars(
        self,
    ) -> None:
        schema = build_propose_flow_tool_schema(resource_catalog=_empty_catalog())

        validate_propose_flow_tool_arguments(
            arguments={
                "flow_name": "Report",
                "flow_description": None,
                "plan_rationale": "Create the report.",
                "steps": [
                    {
                        "name": "Write",
                        "instructions": "Write the report.",
                        "output_fields": None,
                        "model_ref": None,
                        "knowledge_refs": [],
                        "citations_requested": False,
                    }
                ],
                "assumptions": [],
            },
            tool_schema=schema,
        )

    @pytest.mark.parametrize(
        ("property_name", "value"),
        [("output_fields", []), ("knowledge_refs", None)],
    )
    def test_create_step_schema_rejects_invalid_empty_or_nullable_lists(
        self,
        property_name: str,
        value: object,
    ) -> None:
        schema = build_propose_flow_tool_schema(resource_catalog=_empty_catalog())
        step = {
            "name": "Write",
            "instructions": "Write the report.",
            "output_fields": None,
            "model_ref": None,
            "knowledge_refs": [],
            "citations_requested": False,
        }
        step[property_name] = value

        with pytest.raises(ProposalToolArgumentsError):
            validate_propose_flow_tool_arguments(
                arguments={
                    "flow_name": "Report",
                    "flow_description": None,
                    "plan_rationale": "Create the report.",
                    "steps": [step],
                    "assumptions": [],
                },
                tool_schema=schema,
            )

    def test_edit_step_schema_keeps_its_existing_optional_shape(self) -> None:
        schema = build_propose_flow_tool_schema(
            resource_catalog=_empty_catalog(), current_steps=[]
        )
        add_step_schema = schema["function"]["parameters"]["properties"]["steps"][
            "items"
        ]["oneOf"][1]["properties"]["step"]
        field_schema = add_step_schema["properties"]["output_fields"]["items"]

        assert add_step_schema["required"] == ["name", "instructions"]
        assert field_schema["properties"]["name"]["pattern"]
        assert "anyOf" not in field_schema

    @pytest.mark.parametrize(
        ("scope", "retired_key", "retired_value", "expected_path"),
        [
            ("root", "input_fields", [], "input_fields"),
            ("step", "output_type", "text", "steps.0.output_type"),
            ("step", "review_mode", "view", "steps.0.review_mode"),
            ("step", "uses_form_fields", ["case_id"], "steps.0.uses_form_fields"),
            (
                "step",
                "uses_previous_fields",
                [{"from_step": 1, "field_path": "case_id"}],
                "steps.0.uses_previous_fields",
            ),
        ],
    )
    def test_create_parser_rejects_properties_outside_the_typed_create_model(
        self,
        scope: str,
        retired_key: str,
        retired_value: object,
        expected_path: str,
    ) -> None:
        arguments: dict[str, object] = {
            "flow_name": "Report",
            "plan_rationale": "Create the report.",
            "steps": [{"name": "Write", "instructions": "Write the report."}],
        }
        if scope == "root":
            arguments[retired_key] = retired_value
        else:
            steps = arguments["steps"]
            assert isinstance(steps, list)
            step = steps[0]
            assert isinstance(step, dict)
            step[retired_key] = retired_value

        with pytest.raises(ProposalIntentArgumentError, match=expected_path):
            parse_create_flow_intent_arguments(arguments)

    def test_create_parser_rejects_unknown_root_keys_through_the_typed_model(
        self,
    ) -> None:
        with pytest.raises(ProposalIntentArgumentError) as excinfo:
            parse_create_flow_intent_arguments(
                {
                    "flow_name": "Report",
                    "plan_rationale": "Create the report.",
                    "reasoning": "Private model scratchpad",
                    "steps": [
                        {
                            "name": "Write",
                            "instructions": "Write the report.",
                        }
                    ],
                }
            )

        assert excinfo.value.issues == (
            "reasoning: Extra inputs are not permitted [extra_forbidden]",
        )

    def test_active_proposal_schemas_reject_non_object_step_before_normalization(
        self,
    ) -> None:
        schemas = (
            build_propose_flow_tool_schema(resource_catalog=_empty_catalog()),
            build_propose_flow_tool_schema(
                resource_catalog=_empty_catalog(), current_steps=[]
            ),
        )

        for schema in schemas:
            with pytest.raises(ProposalToolArgumentsError):
                validate_propose_flow_tool_arguments(
                    arguments={
                        "flow_name": "Report",
                        "flow_description": None,
                        "plan_rationale": "Create the report.",
                        "steps": ["Write the report"],
                        "assumptions": [],
                    },
                    tool_schema=schema,
                )

    def test_edit_schema_feedback_identifies_the_invalid_branch_field(self) -> None:
        step = FlowStep(
            id=uuid4(),
            flow_id=uuid4(),
            tenant_id=uuid4(),
            assistant_id=uuid4(),
            step_order=1,
            user_description="Compare evidence",
            input_source="flow_input",
            input_type="text",
            output_mode="pass_through",
            output_type="text",
        )
        schema = build_edit_flow_tool_schema(
            [step],
            resource_catalog=_empty_catalog(),
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        )

        with pytest.raises(
            ProposalToolArgumentsError,
            match=r"steps\.0.*flow_name.*additionalProperties",
        ):
            validate_propose_flow_tool_arguments(
                arguments={
                    "plan_rationale": "Update one step.",
                    "steps": [
                        {
                            "kind": "modify",
                            "existing_step_ref": "existing_step_1",
                            "flow_name": "This field belongs at the root",
                        }
                    ],
                },
                tool_schema=schema,
            )

    def test_edit_schema_feedback_prioritizes_a_missing_required_ref(self) -> None:
        step = FlowStep(
            id=uuid4(),
            flow_id=uuid4(),
            tenant_id=uuid4(),
            assistant_id=uuid4(),
            step_order=1,
            user_description="Compare evidence",
            input_source="flow_input",
            input_type="text",
            output_mode="pass_through",
            output_type="text",
        )
        schema = build_edit_flow_tool_schema(
            [step],
            resource_catalog=_empty_catalog(),
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        )

        with pytest.raises(
            ProposalToolArgumentsError,
            match=r"steps\.0.*existing_step_ref.*required",
        ):
            validate_propose_flow_tool_arguments(
                arguments={
                    "plan_rationale": "Update one step.",
                    "steps": [{"kind": "modify", "input_type": "unsupported"}],
                },
                tool_schema=schema,
            )


class TestParseToolCallArguments:
    def test_parse_tool_call_arguments_accepts_json_object(self) -> None:
        assert parse_tool_call_arguments('{"plan_rationale":"Create"}') == {
            "plan_rationale": "Create"
        }

    def test_parse_tool_call_arguments_rejects_malformed_json(self) -> None:
        with pytest.raises(ToolArgumentParseError, match="Expecting property name"):
            parse_tool_call_arguments("{not json")

    @pytest.mark.parametrize("arguments", ["[1, 2]", '"text"', "3", "null"])
    def test_parse_tool_call_arguments_rejects_non_object_json(
        self, arguments: str
    ) -> None:
        with pytest.raises(ToolArgumentParseError, match="JSON object"):
            parse_tool_call_arguments(arguments)


class TestExtractHelpers:
    def test_extract_helpers_ignore_wrong_shapes(self) -> None:
        arguments = {
            "assumptions": ["A", 123, "B"],
            "plan_rationale": "Rationale",
        }

        assert extract_assumptions(arguments) == ["A", "B"]
        assert extract_plan_rationale(arguments) == "Rationale"
