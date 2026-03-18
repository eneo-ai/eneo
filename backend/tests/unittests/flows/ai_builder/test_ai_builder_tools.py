"""Tests for AI Builder tool schemas."""

from __future__ import annotations

import pytest

from intric.flows.ai_builder.ai_builder_models import FlowDraftSpecCore
from intric.flows.ai_builder.ai_builder_tools import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
    PROPOSE_FLOW_TOOL_NAME,
    VALIDATE_FLOW_DRAFT_TOOL_NAME,
    build_all_tool_schemas,
    build_ask_structured_question_tool_schema,
    build_propose_flow_tool_schema,
    build_validate_flow_draft_tool_schema,
    extract_assumptions,
    extract_plan_rationale,
    extract_reasoning,
    parse_propose_flow_arguments,
    parse_structured_question,
)


class TestBuildToolSchema:
    def test_schema_has_function_format(self) -> None:
        schema = build_propose_flow_tool_schema()
        assert schema["type"] == "function"
        assert "function" in schema
        assert schema["function"]["name"] == PROPOSE_FLOW_TOOL_NAME

    def test_schema_has_parameters(self) -> None:
        schema = build_propose_flow_tool_schema()
        params = schema["function"]["parameters"]
        assert params["type"] == "object"
        assert "flow_name" in params["properties"]
        assert "steps" in params["properties"]

    def test_schema_required_fields(self) -> None:
        schema = build_propose_flow_tool_schema()
        required = schema["function"]["parameters"]["required"]
        assert "flow_name" in required
        assert "steps" in required

    def test_step_schema_has_required_fields(self) -> None:
        schema = build_propose_flow_tool_schema()
        step_schema = schema["function"]["parameters"]["properties"]["steps"]["items"]
        assert "plan_step_ref" in step_schema["required"]
        assert "name" in step_schema["required"]
        assert "assistant_spec" in step_schema["required"]
        assert "input_source" in step_schema["required"]

    def test_schema_includes_enum_values(self) -> None:
        schema = build_propose_flow_tool_schema()
        step_props = schema["function"]["parameters"]["properties"]["steps"]["items"]["properties"]
        assert "flow_input" in step_props["input_source"]["enum"]
        assert "previous_step" in step_props["input_source"]["enum"]

    def test_schema_min_items_on_steps(self) -> None:
        schema = build_propose_flow_tool_schema()
        steps = schema["function"]["parameters"]["properties"]["steps"]
        assert steps["minItems"] == 1
        assert steps["maxItems"] == 12

    def test_schema_has_reasoning_field(self) -> None:
        schema = build_propose_flow_tool_schema()
        props = schema["function"]["parameters"]["properties"]
        assert "reasoning" in props
        # reasoning should be first property (appears before flow_name)
        prop_keys = list(props.keys())
        assert prop_keys[0] == "reasoning"

    def test_reasoning_not_required(self) -> None:
        schema = build_propose_flow_tool_schema()
        required = schema["function"]["parameters"]["required"]
        assert "reasoning" not in required

    def test_input_bindings_schema_is_tightened(self) -> None:
        schema = build_propose_flow_tool_schema()
        input_bindings = (
            schema["function"]["parameters"]["properties"]["steps"]["items"]["properties"]["input_bindings"]
        )
        assert input_bindings["required"] == ["question"]
        assert input_bindings["additionalProperties"] is False
        assert input_bindings["properties"]["question"]["minLength"] == 1

    def test_schema_descriptions_align_with_runtime_input_and_step_refs(self) -> None:
        schema = build_propose_flow_tool_schema()
        step_props = schema["function"]["parameters"]["properties"]["steps"]["items"]["properties"]
        assert "Do not use runtime refs like step_1" in step_props["plan_step_ref"]["description"]
        assert "{{ step_input.text }}" in step_props["input_bindings"]["description"]
        assert "output.structured" in step_props["input_bindings"]["properties"]["question"]["description"]
        assert "{{ step_input.text }}" in step_props["input_config"]["description"]

    def test_knowledge_refs_require_unique_items(self) -> None:
        schema = build_propose_flow_tool_schema()
        knowledge_refs = (
            schema["function"]["parameters"]["properties"]["steps"]["items"]["properties"]["assistant_spec"]["properties"]["knowledge_refs"]
        )
        assert knowledge_refs["uniqueItems"] is True


class TestParseArguments:
    def test_parse_minimal_valid(self) -> None:
        args = {
            "flow_name": "My Flow",
            "steps": [
                {
                    "plan_step_ref": "step_a",
                    "name": "Extract",
                    "assistant_spec": {"instructions": "Extract data"},
                    "input_source": "flow_input",
                },
            ],
        }
        spec = parse_propose_flow_arguments(args)
        assert isinstance(spec, FlowDraftSpecCore)
        assert spec.flow_name == "My Flow"
        assert len(spec.steps) == 1

    def test_parse_multi_step(self) -> None:
        args = {
            "flow_name": "Pipeline",
            "flow_description": "A 3-step pipeline",
            "steps": [
                {
                    "plan_step_ref": "step_a",
                    "name": "Input",
                    "assistant_spec": {"instructions": "Read"},
                    "input_source": "flow_input",
                    "input_type": "text",
                },
                {
                    "plan_step_ref": "step_b",
                    "name": "Process",
                    "assistant_spec": {"instructions": "Process"},
                    "input_source": "previous_step",
                },
                {
                    "plan_step_ref": "step_c",
                    "name": "Output",
                    "assistant_spec": {"instructions": "Summarize"},
                    "input_source": "previous_step",
                    "output_type": "json",
                },
            ],
        }
        spec = parse_propose_flow_arguments(args)
        assert len(spec.steps) == 3
        assert spec.steps[2].output_type.value == "json"

    def test_parse_with_all_optional_fields(self) -> None:
        args = {
            "flow_name": "Full",
            "steps": [
                {
                    "plan_step_ref": "step_a",
                    "name": "Step",
                    "assistant_spec": {
                        "instructions": "Do it",
                        "model_ref": "gpt-4",
                        "knowledge_refs": ["kb1"],
                    },
                    "input_source": "flow_input",
                    "input_type": "audio",
                    "output_mode": "transcribe_only",
                    "output_type": "text",
                    "mcp_policy": "restricted",
                    "input_bindings": {"question": "test"},
                },
            ],
        }
        spec = parse_propose_flow_arguments(args)
        assert spec.steps[0].mcp_policy.value == "restricted"
        assert spec.steps[0].assistant_spec.model_ref == "gpt-4"

    def test_parse_invalid_raises(self) -> None:
        with pytest.raises(Exception):
            parse_propose_flow_arguments({"flow_name": "No steps"})

    def test_parse_invalid_enum_raises(self) -> None:
        args = {
            "flow_name": "Bad",
            "steps": [
                {
                    "plan_step_ref": "step_a",
                    "name": "Step",
                    "assistant_spec": {"instructions": "Do it"},
                    "input_source": "nonexistent_source",
                },
            ],
        }
        with pytest.raises(Exception):
            parse_propose_flow_arguments(args)

    def test_parse_accepts_spec_wrapper(self) -> None:
        args = {
            "spec": {
                "flow_name": "Wrapped Flow",
                "steps": [
                    {
                        "plan_step_ref": "step_a",
                        "name": "Extract",
                        "assistant_spec": {"instructions": "Extract data"},
                        "input_source": "flow_input",
                    },
                ],
            }
        }

        spec = parse_propose_flow_arguments(args)

        assert spec.flow_name == "Wrapped Flow"
        assert len(spec.steps) == 1

    def test_parse_accepts_draft_wrapper(self) -> None:
        args = {
            "draft": {
                "flow_name": "Wrapped Draft",
                "steps": [
                    {
                        "plan_step_ref": "step_a",
                        "name": "Extract",
                        "assistant_spec": {"instructions": "Extract data"},
                        "input_source": "flow_input",
                    },
                ],
            }
        }

        spec = parse_propose_flow_arguments(args)

        assert spec.flow_name == "Wrapped Draft"
        assert len(spec.steps) == 1


class TestExtractAssumptions:
    def test_extracts_strings(self) -> None:
        args = {"assumptions": ["User wants PDF", "Swedish output"]}
        result = extract_assumptions(args)
        assert result == ["User wants PDF", "Swedish output"]

    def test_empty_list(self) -> None:
        assert extract_assumptions({"assumptions": []}) == []

    def test_missing_key(self) -> None:
        assert extract_assumptions({}) == []

    def test_filters_non_strings(self) -> None:
        args = {"assumptions": ["Valid", 123, None, "Also valid"]}
        result = extract_assumptions(args)
        assert result == ["Valid", "Also valid"]


class TestExtractReasoning:
    def test_extracts_string(self) -> None:
        args = {"reasoning": "Step 1 needs flow_input, step 2 uses previous_step"}
        result = extract_reasoning(args)
        assert result == "Step 1 needs flow_input, step 2 uses previous_step"

    def test_missing_key(self) -> None:
        assert extract_reasoning({}) is None

    def test_empty_string(self) -> None:
        assert extract_reasoning({"reasoning": ""}) is None

    def test_non_string(self) -> None:
        assert extract_reasoning({"reasoning": 123}) is None


class TestParseStripsNonSpecFields:
    def test_reasoning_stripped_before_validation(self) -> None:
        args = {
            "reasoning": "The user wants a simple extraction flow",
            "flow_name": "Test",
            "steps": [
                {
                    "plan_step_ref": "step_a",
                    "name": "Extract",
                    "assistant_spec": {"instructions": "Extract data"},
                    "input_source": "flow_input",
                },
            ],
        }
        spec = parse_propose_flow_arguments(args)
        assert spec.flow_name == "Test"
        # reasoning should not end up on the spec
        assert not hasattr(spec, "reasoning")

    def test_assumptions_stripped_before_validation(self) -> None:
        args = {
            "assumptions": ["User wants text output"],
            "flow_name": "Test",
            "steps": [
                {
                    "plan_step_ref": "step_a",
                    "name": "Step",
                    "assistant_spec": {"instructions": "Do it"},
                    "input_source": "flow_input",
                },
            ],
        }
        spec = parse_propose_flow_arguments(args)
        assert spec.flow_name == "Test"


class TestBuildAskStructuredQuestionSchema:
    def test_schema_has_function_format(self) -> None:
        schema = build_ask_structured_question_tool_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == ASK_STRUCTURED_QUESTION_TOOL_NAME

    def test_required_fields(self) -> None:
        schema = build_ask_structured_question_tool_schema()
        required = schema["function"]["parameters"]["required"]
        assert "question_id" in required
        assert "question" in required
        assert "options" in required

    def test_options_constraints(self) -> None:
        schema = build_ask_structured_question_tool_schema()
        options = schema["function"]["parameters"]["properties"]["options"]
        assert options["minItems"] == 2
        assert options["maxItems"] == 8

    def test_selection_mode_enum(self) -> None:
        schema = build_ask_structured_question_tool_schema()
        mode = schema["function"]["parameters"]["properties"]["selection_mode"]
        assert mode["enum"] == ["single", "multi"]

    def test_schema_supports_question_metadata(self) -> None:
        schema = build_ask_structured_question_tool_schema()
        props = schema["function"]["parameters"]["properties"]
        assert "question_id" in props
        assert "final_output_mode" in props["question_id"]["enum"]
        assert "id" in props["options"]["items"]["properties"]
        assert "value" in props["options"]["items"]["properties"]


class TestBuildValidateDraftToolSchema:
    def test_schema_has_function_format(self) -> None:
        schema = build_validate_flow_draft_tool_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == VALIDATE_FLOW_DRAFT_TOOL_NAME

    def test_schema_reuses_flow_spec_shape(self) -> None:
        schema = build_validate_flow_draft_tool_schema()
        props = schema["function"]["parameters"]["properties"]
        assert "flow_name" in props
        assert "steps" in props
        assert "form_fields" in props


class TestParseStructuredQuestion:
    def test_minimal_valid(self) -> None:
        args = {
            "question_id": "final_output_mode",
            "question": "Which format?",
            "options": [{"label": "JSON"}, {"label": "Text"}],
        }
        result = parse_structured_question(args)
        assert result["question_id"] == "final_output_mode"
        assert result["question"] == "Which format?"
        assert len(result["options"]) == 2
        assert result["selection_mode"] == "single"
        assert result["allow_custom"] is True

    def test_with_all_fields(self) -> None:
        args = {
            "question_id": "input_material_mode",
            "question": "Pick sources",
            "options": [
                {"label": "PDF", "description": "Upload a PDF file"},
                {"label": "URL", "description": "Paste a URL"},
                {"label": "Text"},
            ],
            "selection_mode": "multi",
            "allow_custom": False,
        }
        result = parse_structured_question(args)
        assert result["selection_mode"] == "multi"
        assert result["allow_custom"] is False
        assert result["options"][0]["description"] == "Upload a PDF file"
        assert result["options"][2]["description"] is None

    def test_preserves_option_ids_and_values(self) -> None:
        args = {
            "question_id": "document_material_scope",
            "question": "How many PDFs?",
            "options": [
                {
                    "id": "single",
                    "label": "One PDF",
                    "value": {"mode": "single"},
                    "description": "Simpler flow",
                },
                {
                    "id": "multi",
                    "label": "Multiple PDFs",
                    "value": {"mode": "multi"},
                },
            ],
        }
        result = parse_structured_question(args)
        assert result["question_id"] == "document_material_scope"
        assert result["options"][0]["id"] == "single"
        assert result["options"][0]["value"] == {"mode": "single"}
        assert result["options"][1]["id"] == "multi"
        assert result["options"][1]["value"] == {"mode": "multi"}

    def test_empty_question_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty string"):
            parse_structured_question(
                {
                    "question_id": "final_output_mode",
                    "question": "",
                    "options": [{"label": "A"}, {"label": "B"}],
                }
            )

    def test_missing_question_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty string"):
            parse_structured_question(
                {
                    "question_id": "final_output_mode",
                    "options": [{"label": "A"}, {"label": "B"}],
                }
            )

    def test_too_few_options_raises(self) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            parse_structured_question(
                {
                    "question_id": "final_output_mode",
                    "question": "Pick one",
                    "options": [{"label": "A"}],
                }
            )

    def test_option_without_label_raises(self) -> None:
        with pytest.raises(ValueError, match="string 'label'"):
            parse_structured_question(
                {
                    "question_id": "final_output_mode",
                    "question": "Pick",
                    "options": [{"label": "A"}, {"desc": "no label"}],
                }
            )

    def test_strips_whitespace_from_question(self) -> None:
        result = parse_structured_question({
            "question_id": "final_output_mode",
            "question": "  Which?  ",
            "options": [{"label": "A"}, {"label": "B"}],
        })
        assert result["question"] == "Which?"

    def test_missing_question_id_raises(self) -> None:
        with pytest.raises(ValueError, match="question_id"):
            parse_structured_question({
                "question": "Which?",
                "options": [{"label": "A"}, {"label": "B"}],
            })

    def test_unsupported_question_id_raises(self) -> None:
        with pytest.raises(ValueError, match="supported canonical AI Builder ids"):
            parse_structured_question({
                "question_id": "custom_question_branch",
                "question": "Which?",
                "options": [{"label": "A"}, {"label": "B"}],
            })

    def test_invalid_selection_mode_raises(self) -> None:
        with pytest.raises(ValueError, match="selection_mode"):
            parse_structured_question({
                "question_id": "final_output_mode",
                "question": "Which?",
                "options": [{"label": "A"}, {"label": "B"}],
                "selection_mode": "many",
            })

    def test_non_boolean_allow_custom_raises(self) -> None:
        with pytest.raises(ValueError, match="allow_custom"):
            parse_structured_question({
                "question_id": "final_output_mode",
                "question": "Which?",
                "options": [{"label": "A"}, {"label": "B"}],
                "allow_custom": "yes",
            })


class TestBuildAllToolSchemas:
    def test_returns_all_tools(self) -> None:
        schemas = build_all_tool_schemas()
        assert len(schemas) == 3
        names = {s["function"]["name"] for s in schemas}
        assert PROPOSE_FLOW_TOOL_NAME in names
        assert ASK_STRUCTURED_QUESTION_TOOL_NAME in names
        assert "confirm_requirements" in names


class TestExtractPlanRationale:
    def test_extracts_string(self) -> None:
        args = {"plan_rationale": "Use JSON extraction first for safer downstream bindings."}
        assert extract_plan_rationale(args) == (
            "Use JSON extraction first for safer downstream bindings."
        )

    def test_missing_key(self) -> None:
        assert extract_plan_rationale({}) is None
