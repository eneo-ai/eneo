"""Tests for active AI Builder tool schemas and parsing helpers."""

from __future__ import annotations

import pytest

from intric.flows.ai_builder.ai_builder_tools import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
    CREATE_FLOW_TOOL_NAME,
    build_all_tool_schemas,
    build_ask_structured_question_tool_schema,
    build_create_flow_tool_schema,
    extract_assumptions,
    extract_plan_rationale,
    extract_reasoning,
    parse_create_flow_arguments,
    parse_structured_question,
)


class TestBuildToolSchema:
    def test_create_schema_has_function_format(self) -> None:
        schema = build_create_flow_tool_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == CREATE_FLOW_TOOL_NAME

    def test_create_schema_has_flat_step_fields(self) -> None:
        schema = build_create_flow_tool_schema()
        step_schema = schema["function"]["parameters"]["properties"]["steps"]["items"]
        assert "plan_step_ref" not in step_schema["properties"]
        assert "output_mode" not in step_schema["properties"]
        assert "input_bindings" not in step_schema["properties"]
        assert "output_contract" not in step_schema["properties"]
        assert "instructions" in step_schema["properties"]
        assert "document_delivery_mode" in step_schema["properties"]
        assert "output_fields" in step_schema["properties"]
        assert "uses_previous_fields" in step_schema["properties"]

    def test_create_schema_requires_first_step_to_use_flow_input(self) -> None:
        schema = build_create_flow_tool_schema()
        steps_description = schema["function"]["parameters"]["properties"]["steps"][
            "description"
        ]
        input_source_description = schema["function"]["parameters"]["properties"][
            "steps"
        ]["items"]["properties"]["input_source"]["description"]
        output_fields_description = schema["function"]["parameters"]["properties"][
            "steps"
        ]["items"]["properties"]["output_fields"]["description"]

        assert "First step must use 'flow_input'" in steps_description
        assert "never directly in steps[]" in steps_description
        assert (
            "Only later steps may use 'previous_step' or 'all_previous_steps'"
            in input_source_description
        )
        assert "never directly in steps[]" in output_fields_description

    def test_create_schema_limits_structured_field_depth_and_leaf_shape(self) -> None:
        schema = build_create_flow_tool_schema()
        output_fields = schema["function"]["parameters"]["properties"]["steps"][
            "items"
        ]["properties"]["output_fields"]
        top_level = output_fields["items"]
        level_2 = top_level["properties"]["fields"]["items"]
        level_3 = level_2["properties"]["fields"]["items"]

        assert "max nesting depth 3" in output_fields["description"]
        assert level_3["properties"]["field_type"]["enum"] == [
            "string",
            "number",
            "boolean",
        ]
        assert level_3["properties"]["fields"] is False
        assert level_3["properties"]["item_fields"] is False


class TestParseArguments:
    def test_parse_create_flow_arguments_returns_typed_draft(self) -> None:
        draft = parse_create_flow_arguments(
            {
                "flow_name": "Dokumentanalys",
                "plan_rationale": "Struktur först.",
                "steps": [
                    {
                        "name": "Extrahera",
                        "instructions": "Extrahera strukturerad data.",
                        "input_source": "flow_input",
                        "input_type": "document",
                        "output_type": "json",
                        "runtime_upload": True,
                        "runtime_required": True,
                        "output_fields": [
                            {
                                "name": "risknivå",
                                "field_type": "string",
                                "description": "Risknivå.",
                                "required": True,
                            }
                        ],
                    },
                    {
                        "name": "Skriv slutrapport",
                        "instructions": "Skriv slutrapport.",
                        "input_source": "previous_step",
                        "input_type": "json",
                        "output_type": "text",
                        "uses_previous_fields": [
                            {
                                "from_step": 1,
                                "field_path": "risknivå",
                                "label": "Risknivå",
                            }
                        ],
                    },
                ],
            }
        )

        assert draft.flow_name == "Dokumentanalys"
        assert draft.steps[0].runtime_upload is True
        assert draft.steps[0].output_fields is not None
        assert draft.steps[0].output_fields[0].name == "risknivå"
        assert draft.steps[1].uses_previous_fields[0].field_path == "risknivå"

    def test_parse_create_flow_arguments_allows_three_level_structured_fields(
        self,
    ) -> None:
        draft = parse_create_flow_arguments(
            {
                "flow_name": "Dokumentanalys",
                "plan_rationale": "Struktur först.",
                "steps": [
                    {
                        "name": "Extrahera risker",
                        "instructions": "Extrahera risker som strukturerad JSON.",
                        "input_source": "flow_input",
                        "input_type": "document",
                        "output_type": "json",
                        "runtime_upload": True,
                        "runtime_required": True,
                        "output_fields": [
                            {
                                "name": "risker",
                                "field_type": "array",
                                "description": "Identifierade risker.",
                                "required": True,
                                "item_fields": [
                                    {
                                        "name": "rubrik",
                                        "field_type": "string",
                                        "description": "Riskrubrik.",
                                        "required": True,
                                    },
                                    {
                                        "name": "ekonomisk_konsekvens",
                                        "field_type": "object",
                                        "description": "Ekonomisk konsekvens.",
                                        "required": False,
                                        "fields": [
                                            {
                                                "name": "kort_sikt",
                                                "field_type": "string",
                                                "description": "Kort sikt.",
                                                "required": False,
                                            }
                                        ],
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        )

        risk_field = draft.steps[0].output_fields[0]
        assert risk_field.item_fields is not None
        assert risk_field.item_fields[1].fields is not None
        assert risk_field.item_fields[1].fields[0].name == "kort_sikt"

    def test_parse_create_flow_arguments_rejects_fourth_level_structured_fields(
        self,
    ) -> None:
        with pytest.raises(Exception, match="nesting depth cannot exceed 3"):
            parse_create_flow_arguments(
                {
                    "flow_name": "Dokumentanalys",
                    "plan_rationale": "Struktur först.",
                    "steps": [
                        {
                            "name": "Extrahera risker",
                            "instructions": "Extrahera risker som strukturerad JSON.",
                            "input_source": "flow_input",
                            "input_type": "document",
                            "output_type": "json",
                            "runtime_upload": True,
                            "runtime_required": True,
                            "output_fields": [
                                {
                                    "name": "risker",
                                    "field_type": "array",
                                    "description": "Identifierade risker.",
                                    "required": True,
                                    "item_fields": [
                                        {
                                            "name": "ekonomisk_konsekvens",
                                            "field_type": "object",
                                            "description": "Ekonomisk konsekvens.",
                                            "required": False,
                                            "fields": [
                                                {
                                                    "name": "kort_sikt",
                                                    "field_type": "object",
                                                    "description": "Kort sikt.",
                                                    "required": False,
                                                    "fields": [
                                                        {
                                                            "name": "belopp",
                                                            "field_type": "number",
                                                            "description": "Belopp.",
                                                            "required": False,
                                                        }
                                                    ],
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            )

    def test_parse_create_flow_arguments_rejects_structured_field_entries_in_steps_array(
        self,
    ) -> None:
        with pytest.raises(
            Exception,
            match=r"steps\[1\] looks like a structured output field, not a step",
        ):
            parse_create_flow_arguments(
                {
                    "flow_name": "Dokumentanalys",
                    "plan_rationale": "Struktur först.",
                    "steps": [
                        {
                            "name": "Sammanfatta underlag",
                            "instructions": "Skriv en sammanfattning.",
                            "input_source": "flow_input",
                            "input_type": "document",
                            "output_type": "text",
                        },
                        {
                            "name": "osakerheter_och_risker",
                            "field_type": "string",
                            "description": "Osäkerheter och risker.",
                            "required": True,
                        },
                    ],
                }
            )

    def test_parse_create_flow_arguments_normalizes_structured_field_entries_into_previous_json_step(
        self,
    ) -> None:
        draft = parse_create_flow_arguments(
            {
                "flow_name": "Dokumentanalys",
                "plan_rationale": "Struktur först.",
                "steps": [
                    {
                        "name": "Extrahera risker",
                        "instructions": "Extrahera risker som strukturerad JSON.",
                        "input_source": "flow_input",
                        "input_type": "document",
                        "output_type": "json",
                        "runtime_upload": True,
                        "runtime_required": True,
                        "output_fields": [
                            {
                                "name": "risker",
                                "field_type": "string",
                                "description": "Identifierade risker.",
                                "required": True,
                            }
                        ],
                    },
                    {
                        "name": "osakerheter_och_risker",
                        "field_type": "string",
                        "description": "Osäkerheter och risker.",
                        "required": True,
                    },
                ],
            }
        )

        assert len(draft.steps) == 1
        assert draft.steps[0].output_fields is not None
        assert [field.name for field in draft.steps[0].output_fields] == [
            "risker",
            "osakerheter_och_risker",
        ]

    def test_parse_create_flow_arguments_rejects_structured_field_entries_in_steps_array_without_json_parent(
        self,
    ) -> None:
        with pytest.raises(
            Exception,
            match=r"steps\[1\] looks like a structured output field, not a step",
        ):
            parse_create_flow_arguments(
                {
                    "flow_name": "Dokumentanalys",
                    "plan_rationale": "Struktur först.",
                    "steps": [
                        {
                            "name": "Extrahera risker",
                            "instructions": "Extrahera risker som text.",
                            "input_source": "flow_input",
                            "input_type": "document",
                            "output_type": "text",
                        },
                        {
                            "name": "osakerheter_och_risker",
                            "field_type": "string",
                            "description": "Osäkerheter och risker.",
                            "required": True,
                        },
                    ],
                }
            )

    def test_parse_create_flow_arguments_rejects_input_bindings_in_step(self) -> None:
        """The tool schema forbids input_bindings — the compiler owns underlag
        composition. Silently ignoring the key let planner templates smuggle
        their own {{ step_n.output.text }} templates past the authoring IR and
        break the compiler's XML-wrap attribution contract. Reject at parse
        time with an actionable message so the repair loop can re-emit.
        """
        with pytest.raises(
            Exception,
            match=r"steps\[0\] contains forbidden key 'input_bindings'",
        ):
            parse_create_flow_arguments(
                {
                    "flow_name": "Dokumentanalys",
                    "plan_rationale": "Struktur först.",
                    "steps": [
                        {
                            "name": "Extrahera risker",
                            "instructions": "Extrahera risker från dokumentet.",
                            "input_source": "flow_input",
                            "input_type": "document",
                            "output_type": "text",
                            "input_bindings": {
                                "question": "{{ step_1.output.text }}",
                            },
                        }
                    ],
                }
            )

    def test_parse_create_flow_arguments_rejects_plan_step_ref_in_step(self) -> None:
        """plan_step_ref is a builder-internal reference. It has no place in the
        authoring IR and was already excluded by build_create_flow_tool_schema.
        Make the exclusion hard — a planner that smuggles it gets a parse-time
        rejection, not silent acceptance.
        """
        with pytest.raises(
            Exception,
            match=r"steps\[0\] contains forbidden key 'plan_step_ref'",
        ):
            parse_create_flow_arguments(
                {
                    "flow_name": "Dokumentanalys",
                    "plan_rationale": "Struktur först.",
                    "steps": [
                        {
                            "name": "Extrahera risker",
                            "instructions": "Extrahera risker från dokumentet.",
                            "input_source": "flow_input",
                            "input_type": "document",
                            "output_type": "text",
                            "plan_step_ref": "step_1",
                        }
                    ],
                }
            )

    def test_parse_create_flow_arguments_rejects_template_tokens_in_plan_rationale(
        self,
    ) -> None:
        """plan_rationale is free-form prose. Template-variable substrings there
        indicate the planner leaked authoring templates into the rationale
        instead of delegating to the compiler.
        """
        with pytest.raises(
            Exception,
            match=r"plan_rationale must not contain template variables",
        ):
            parse_create_flow_arguments(
                {
                    "flow_name": "Dokumentanalys",
                    "plan_rationale": "Vi bygger på {{ step_1.output.text }}.",
                    "steps": [
                        {
                            "name": "Extrahera risker",
                            "instructions": "Extrahera risker från dokumentet.",
                            "input_source": "flow_input",
                            "input_type": "document",
                            "output_type": "text",
                        }
                    ],
                }
            )

    def test_parse_create_flow_arguments_rejects_top_level_input_bindings(self) -> None:
        """Top-level input_bindings (sibling to steps) is also not permitted."""
        with pytest.raises(
            Exception,
            match=r"Flow draft contains forbidden key 'input_bindings'",
        ):
            parse_create_flow_arguments(
                {
                    "flow_name": "Dokumentanalys",
                    "plan_rationale": "Struktur först.",
                    "input_bindings": {"question": "underlag"},
                    "steps": [
                        {
                            "name": "Extrahera risker",
                            "instructions": "Extrahera risker från dokumentet.",
                            "input_source": "flow_input",
                            "input_type": "document",
                            "output_type": "text",
                        }
                    ],
                }
            )


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
        result = parse_structured_question(
            {
                "question_id": "final_output_mode",
                "question": "  Which?  ",
                "options": [{"label": "A"}, {"label": "B"}],
            }
        )
        assert result["question"] == "Which?"

    def test_missing_question_id_raises(self) -> None:
        with pytest.raises(ValueError, match="question_id"):
            parse_structured_question(
                {
                    "question": "Which?",
                    "options": [{"label": "A"}, {"label": "B"}],
                }
            )

    def test_unsupported_question_id_raises(self) -> None:
        with pytest.raises(ValueError, match="supported canonical AI Builder ids"):
            parse_structured_question(
                {
                    "question_id": "custom_question_branch",
                    "question": "Which?",
                    "options": [{"label": "A"}, {"label": "B"}],
                }
            )

    def test_invalid_selection_mode_raises(self) -> None:
        with pytest.raises(ValueError, match="selection_mode"):
            parse_structured_question(
                {
                    "question_id": "final_output_mode",
                    "question": "Which?",
                    "options": [{"label": "A"}, {"label": "B"}],
                    "selection_mode": "many",
                }
            )

    def test_non_boolean_allow_custom_raises(self) -> None:
        with pytest.raises(ValueError, match="allow_custom"):
            parse_structured_question(
                {
                    "question_id": "final_output_mode",
                    "question": "Which?",
                    "options": [{"label": "A"}, {"label": "B"}],
                    "allow_custom": "yes",
                }
            )


class TestBuildAllToolSchemas:
    def test_returns_all_tools(self) -> None:
        schemas = build_all_tool_schemas()
        assert len(schemas) == 3
        names = {schema["function"]["name"] for schema in schemas}
        assert CREATE_FLOW_TOOL_NAME in names
        assert ASK_STRUCTURED_QUESTION_TOOL_NAME in names
        assert "confirm_requirements" in names


class TestExtractPlanRationale:
    def test_extracts_string(self) -> None:
        args = {
            "plan_rationale": "Use JSON extraction first for safer downstream bindings."
        }
        assert extract_plan_rationale(args) == (
            "Use JSON extraction first for safer downstream bindings."
        )

    def test_missing_key(self) -> None:
        assert extract_plan_rationale({}) is None
