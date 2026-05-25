"""Tests for confirm_requirements tool: schema, parser, and SSE event."""

from __future__ import annotations

import json

import pytest

from intric.flows.ai_builder.ai_builder_event_models import (
    RequirementsSummaryPayload,
)
from intric.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_REQUIREMENTS_SUMMARY,
    build_requirements_summary_event,
)
from intric.flows.ai_builder.ai_builder_tools import (
    CONFIRM_REQUIREMENTS_TOOL_NAME,
    OUTLINE_FLOW_TOOL_NAME,
    build_all_tool_schemas,
    build_confirm_requirements_tool_schema,
    parse_confirm_requirements,
)

# ---------------------------------------------------------------------------
# Tool schema
# ---------------------------------------------------------------------------


class TestBuildConfirmRequirementsSchema:
    def test_schema_has_function_format(self) -> None:
        schema = build_confirm_requirements_tool_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == CONFIRM_REQUIREMENTS_TOOL_NAME

    def test_required_fields(self) -> None:
        schema = build_confirm_requirements_tool_schema()
        required = schema["function"]["parameters"]["required"]
        assert "summary" in required
        assert "key_decisions" in required
        assert "input_description" in required
        assert "output_description" in required

    def test_manual_setup_notes_is_optional(self) -> None:
        schema = build_confirm_requirements_tool_schema()
        required = schema["function"]["parameters"]["required"]
        assert "manual_setup_notes" not in required

    def test_key_decisions_items_have_required_fields(self) -> None:
        schema = build_confirm_requirements_tool_schema()
        items = schema["function"]["parameters"]["properties"]["key_decisions"]["items"]
        assert "topic" in items["required"]
        assert "decision" in items["required"]


class TestBuildAllToolSchemasIncludesConfirmRequirements:
    def test_includes_confirm_requirements(self) -> None:
        schemas = build_all_tool_schemas()
        names = {s["function"]["name"] for s in schemas}
        assert CONFIRM_REQUIREMENTS_TOOL_NAME in names
        assert OUTLINE_FLOW_TOOL_NAME in names
        assert "create_flow" not in names

    def test_returns_three_tools(self) -> None:
        schemas = build_all_tool_schemas()
        assert len(schemas) == 3


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class TestParseConfirmRequirements:
    def test_minimal_valid(self) -> None:
        args = {
            "summary": "A flow that extracts data from PDFs.",
            "key_decisions": [
                {"topic": "Input", "decision": "Multiple PDFs per run"},
            ],
            "input_description": "PDF documents uploaded by the user.",
            "output_description": "A DOCX report with comparative analysis.",
        }
        result = parse_confirm_requirements(args)
        assert result["summary"] == "A flow that extracts data from PDFs."
        assert len(result["key_decisions"]) == 1
        assert result["key_decisions"][0]["topic"] == "Input"
        assert result["input_description"] == "PDF documents uploaded by the user."
        assert (
            result["output_description"] == "A DOCX report with comparative analysis."
        )
        assert result["manual_setup_notes"] == []

    def test_with_manual_setup_notes(self) -> None:
        args = {
            "summary": "A flow.",
            "key_decisions": [{"topic": "A", "decision": "B"}],
            "input_description": "Text input.",
            "output_description": "JSON output.",
            "manual_setup_notes": [
                "Connect knowledge base with policy documents.",
                "Upload DOCX template for final report.",
            ],
        }
        result = parse_confirm_requirements(args)
        assert len(result["manual_setup_notes"]) == 2
        assert "knowledge base" in result["manual_setup_notes"][0]

    def test_empty_summary_raises(self) -> None:
        with pytest.raises(ValueError, match="summary"):
            parse_confirm_requirements(
                {
                    "summary": "",
                    "key_decisions": [{"topic": "A", "decision": "B"}],
                    "input_description": "X",
                    "output_description": "Y",
                }
            )

    def test_missing_summary_raises(self) -> None:
        with pytest.raises(ValueError, match="summary"):
            parse_confirm_requirements(
                {
                    "key_decisions": [{"topic": "A", "decision": "B"}],
                    "input_description": "X",
                    "output_description": "Y",
                }
            )

    def test_empty_key_decisions_raises(self) -> None:
        with pytest.raises(ValueError, match="key_decisions"):
            parse_confirm_requirements(
                {
                    "summary": "A flow.",
                    "key_decisions": [],
                    "input_description": "X",
                    "output_description": "Y",
                }
            )

    def test_key_decision_missing_topic_raises(self) -> None:
        with pytest.raises(ValueError, match="topic"):
            parse_confirm_requirements(
                {
                    "summary": "A flow.",
                    "key_decisions": [{"decision": "B"}],
                    "input_description": "X",
                    "output_description": "Y",
                }
            )

    def test_key_decision_missing_decision_raises(self) -> None:
        with pytest.raises(ValueError, match="decision"):
            parse_confirm_requirements(
                {
                    "summary": "A flow.",
                    "key_decisions": [{"topic": "A"}],
                    "input_description": "X",
                    "output_description": "Y",
                }
            )

    def test_missing_input_description_raises(self) -> None:
        with pytest.raises(ValueError, match="input_description"):
            parse_confirm_requirements(
                {
                    "summary": "A flow.",
                    "key_decisions": [{"topic": "A", "decision": "B"}],
                    "output_description": "Y",
                }
            )

    def test_missing_output_description_raises(self) -> None:
        with pytest.raises(ValueError, match="output_description"):
            parse_confirm_requirements(
                {
                    "summary": "A flow.",
                    "key_decisions": [{"topic": "A", "decision": "B"}],
                    "input_description": "X",
                }
            )

    def test_strips_whitespace(self) -> None:
        args = {
            "summary": "  A flow.  ",
            "key_decisions": [{"topic": "  A  ", "decision": "  B  "}],
            "input_description": "  X  ",
            "output_description": "  Y  ",
        }
        result = parse_confirm_requirements(args)
        assert result["summary"] == "A flow."
        assert result["key_decisions"][0]["topic"] == "A"
        assert result["key_decisions"][0]["decision"] == "B"
        assert result["input_description"] == "X"
        assert result["output_description"] == "Y"

    def test_multiple_key_decisions(self) -> None:
        args = {
            "summary": "A flow.",
            "key_decisions": [
                {"topic": "Input", "decision": "PDF documents"},
                {"topic": "Output", "decision": "DOCX report"},
                {"topic": "Mode", "decision": "Without template"},
            ],
            "input_description": "PDFs",
            "output_description": "DOCX",
        }
        result = parse_confirm_requirements(args)
        assert len(result["key_decisions"]) == 3

    def test_filters_non_string_manual_notes(self) -> None:
        args = {
            "summary": "A flow.",
            "key_decisions": [{"topic": "A", "decision": "B"}],
            "input_description": "X",
            "output_description": "Y",
            "manual_setup_notes": ["Valid note", 123, None, "Another valid"],
        }
        result = parse_confirm_requirements(args)
        assert result["manual_setup_notes"] == ["Valid note", "Another valid"]


# ---------------------------------------------------------------------------
# SSE event
# ---------------------------------------------------------------------------


class TestRequirementsSummaryEvent:
    def test_event_type_constant(self) -> None:
        assert SSE_EVENT_REQUIREMENTS_SUMMARY == "requirements_summary"

    def test_build_event(self) -> None:
        data = {
            "summary": "A PDF analysis flow.",
            "key_decisions": [{"topic": "Input", "decision": "Multiple PDFs"}],
            "input_description": "PDF uploads",
            "output_description": "DOCX report",
            "manual_setup_notes": ["Connect knowledge base"],
        }
        event = build_requirements_summary_event(
            RequirementsSummaryPayload.model_validate(data)
        )
        assert event["event"] == "requirements_summary"

        payload = json.loads(event["data"])
        assert payload["summary"] == "A PDF analysis flow."
        assert len(payload["key_decisions"]) == 1
        assert payload["input_description"] == "PDF uploads"
        assert payload["output_description"] == "DOCX report"
        assert payload["manual_setup_notes"] == ["Connect knowledge base"]

    def test_build_event_without_manual_notes(self) -> None:
        data = {
            "summary": "A flow.",
            "key_decisions": [{"topic": "A", "decision": "B"}],
            "input_description": "X",
            "output_description": "Y",
        }
        event = build_requirements_summary_event(
            RequirementsSummaryPayload.model_validate(data)
        )
        payload = json.loads(event["data"])
        assert (
            payload.get("manual_setup_notes") is None
            or payload["manual_setup_notes"] == []
        )


# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------


class TestRequirementsSummaryPayload:
    def test_validates_from_dict(self) -> None:
        data = {
            "summary": "A flow.",
            "key_decisions": [{"topic": "A", "decision": "B"}],
            "input_description": "X",
            "output_description": "Y",
        }
        payload = RequirementsSummaryPayload.model_validate(data)
        assert payload.summary == "A flow."
        assert len(payload.key_decisions) == 1
        assert payload.manual_setup_notes == []

    def test_serializes_to_json(self) -> None:
        data = {
            "summary": "A flow.",
            "key_decisions": [{"topic": "A", "decision": "B"}],
            "input_description": "X",
            "output_description": "Y",
            "manual_setup_notes": ["Note"],
        }
        payload = RequirementsSummaryPayload.model_validate(data)
        json_str = payload.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["summary"] == "A flow."
        assert parsed["manual_setup_notes"] == ["Note"]
