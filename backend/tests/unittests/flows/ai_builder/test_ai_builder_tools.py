"""Tests for active AI Builder tool schemas and parsing helpers."""

from __future__ import annotations

import pytest

from intric.flows.ai_builder import ai_builder_tools
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
)
from intric.flows.ai_builder.ai_builder_tools import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
    CONFIRM_REQUIREMENTS_TOOL_NAME,
    PROPOSE_FLOW_TOOL_NAME,
    build_all_tool_schemas,
    build_ask_structured_question_tool_schema,
    build_propose_flow_tool_schema,
    extract_assumptions,
    extract_plan_rationale,
    extract_reasoning,
    parse_structured_question,
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
        assert "active_submission_tool_name" not in ai_builder_tools.__all__
        assert "ActiveSubmissionToolName" not in ai_builder_tools.__all__
        assert "OUTLINE_FLOW_TOOL_NAME" not in ai_builder_tools.__all__
        assert "EDIT_FLOW_TOOL_NAME" not in ai_builder_tools.__all__

    def test_all_tools_expose_only_active_create_contract(self) -> None:
        names = {schema["function"]["name"] for schema in build_all_tool_schemas()}

        assert names == {
            PROPOSE_FLOW_TOOL_NAME,
            ASK_STRUCTURED_QUESTION_TOOL_NAME,
            CONFIRM_REQUIREMENTS_TOOL_NAME,
        }
        assert "create_flow" not in names
        assert "outline_flow" not in names
        assert "edit_flow" not in names

    def test_outline_schema_hides_backend_owned_mechanics(self) -> None:
        schema = build_propose_flow_tool_schema(resource_catalog=_empty_catalog())
        assert schema["function"]["name"] == PROPOSE_FLOW_TOOL_NAME

        properties = schema["function"]["parameters"]["properties"]
        step_properties = properties["steps"]["items"]["properties"]

        assert "input_source" not in step_properties
        assert "input_type" not in step_properties
        assert "input_bindings" not in step_properties
        assert "output_mode" not in step_properties
        assert "plan_step_ref" not in step_properties
        assert "runtime_input" not in properties
        assert "final_output_type" not in properties
        assert "input_fields" in properties

    def test_structured_question_schema_uses_supported_question_ids(self) -> None:
        schema = build_ask_structured_question_tool_schema()
        question_id_schema = schema["function"]["parameters"]["properties"][
            "question_id"
        ]
        assert question_id_schema["enum"]
        assert "final_output_mode" in question_id_schema["enum"]


class TestParseStructuredQuestion:
    def test_parse_structured_question_accepts_valid_question(self) -> None:
        parsed = parse_structured_question(
            {
                "question_id": "final_output_mode",
                "question": "What input will the flow receive?",
                "options": [
                    {"id": "structured_text", "label": "Text", "value": "text"},
                    {"id": "docx_document", "label": "DOCX", "value": "docx"},
                ],
                "selection_mode": "single",
                "allow_custom": True,
            }
        )

        assert parsed["question_id"] == "final_output_mode"
        assert parsed["options"][0]["label"] == "Text"

    def test_parse_structured_question_rejects_unknown_question_id(self) -> None:
        with pytest.raises(ValueError, match="supported canonical"):
            parse_structured_question(
                {
                    "question_id": "invented_question",
                    "question": "Invented?",
                    "options": [{"label": "A"}, {"label": "B"}],
                }
            )


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
