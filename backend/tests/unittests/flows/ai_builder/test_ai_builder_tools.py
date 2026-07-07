"""Tests for active AI Builder tool schemas and parsing helpers."""

from __future__ import annotations

import pytest

from eneo.flows.ai_builder import ai_builder_tool_names, ai_builder_tools
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_tool_parsing import (
    ToolArgumentParseError,
    parse_tool_call_arguments,
)
from eneo.flows.ai_builder.ai_builder_tools import (
    PROPOSE_FLOW_TOOL_NAME,
    build_propose_flow_tool_schema,
    extract_assumptions,
    extract_plan_rationale,
    extract_reasoning,
)


def _empty_catalog() -> AIBuilderResourceCatalog:
    return build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[],
    )


class TestBuildToolSchema:
    def test_single_active_submission_tool_name_is_canonical(self) -> None:
        assert PROPOSE_FLOW_TOOL_NAME == "propose_flow"
        assert "PROPOSE_FLOW_TOOL_NAME" in ai_builder_tools.__all__
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
        assert (
            ai_builder_tool_names.CONFIRM_REQUIREMENTS_TOOL_NAME
            == "confirm_requirements"
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
        assert "uses_previous_fields" not in step_properties
        assert "uses_previous_outputs" not in step_properties
        assert "plan_step_ref" not in step_properties
        assert "runtime_input" not in properties
        assert "final_output_type" not in properties
        assert "input_fields" in properties

    def test_create_parser_strips_model_authored_previous_refs(self) -> None:
        intent = parse_create_flow_intent_arguments(
            {
                "flow_name": "Report",
                "plan_rationale": "Create the report.",
                "steps": [
                    {
                        "name": "Write",
                        "instructions": "Write the report.",
                        "uses_previous_fields": [
                            {"from_step": 99, "field_path": "", "label": ""}
                        ],
                        "uses_previous_outputs": [
                            {"from_step": 99, "output": "structured"}
                        ],
                    }
                ],
            }
        )

        step = intent.steps[0]
        assert step.uses_previous_fields == []
        assert step.uses_previous_outputs == []


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
            "reasoning": "Reason",
            "plan_rationale": "Rationale",
        }

        assert extract_assumptions(arguments) == ["A", "B"]
        assert extract_reasoning(arguments) == "Reason"
        assert extract_plan_rationale(arguments) == "Rationale"
