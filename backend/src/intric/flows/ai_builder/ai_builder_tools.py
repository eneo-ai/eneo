"""Active tool schemas and parser exports for the AI Builder."""

from __future__ import annotations

from typing import Any

from intric.flows.ai_builder.ai_builder_create_outline import (
    OUTLINE_FLOW_TOOL_NAME,
    build_outline_flow_tool_schema,
    parse_outline_flow_arguments,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    supported_structured_question_ids,
)
from intric.flows.ai_builder.ai_builder_tool_parsing import (
    extract_assumptions,
    extract_plan_rationale,
    extract_reasoning,
    parse_confirm_requirements,
    parse_structured_question,
)

ASK_STRUCTURED_QUESTION_TOOL_NAME = "ask_structured_question"

ASK_STRUCTURED_QUESTION_DESCRIPTION = (
    "Ask the user a question with clickable options instead of free text. "
    "Use only for backend-supported canonical discovery questions. "
    "Do not invent new question ids, custom option families, or ad hoc discovery branches."
)

CONFIRM_REQUIREMENTS_TOOL_NAME = "confirm_requirements"

CONFIRM_REQUIREMENTS_DESCRIPTION = (
    "Present your understanding of the user's needs for confirmation before building a plan. "
    "Call this after discovery to summarize what you understood. "
    "The user must confirm before you call outline_flow or edit_flow."
)


def build_ask_structured_question_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": ASK_STRUCTURED_QUESTION_TOOL_NAME,
            "description": ASK_STRUCTURED_QUESTION_DESCRIPTION,
            "parameters": {
                "type": "object",
                "required": ["question_id", "question", "options"],
                "properties": {
                    "question_id": {
                        "type": "string",
                        "enum": list(supported_structured_question_ids()),
                        "description": "Stable identifier for the question.",
                    },
                    "question": {
                        "type": "string",
                        "description": "The question text to display to the user.",
                    },
                    "options": {
                        "type": "array",
                        "description": "Selectable options for the user.",
                        "minItems": 2,
                        "maxItems": 8,
                        "items": {
                            "type": "object",
                            "required": ["label"],
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "description": "Stable option identifier for metadata preservation.",
                                },
                                "label": {
                                    "type": "string",
                                    "description": "Short display label for the option.",
                                },
                                "value": {
                                    "description": "Optional machine-readable value to preserve in metadata.",
                                },
                                "description": {
                                    "type": "string",
                                    "description": "Optional longer description.",
                                },
                            },
                        },
                    },
                    "selection_mode": {
                        "type": "string",
                        "enum": ["single", "multi"],
                        "default": "single",
                        "description": "Whether user picks one or multiple options.",
                    },
                    "allow_custom": {
                        "type": "boolean",
                        "default": True,
                        "description": "Whether to show an 'Other...' free text escape hatch.",
                    },
                },
            },
        },
    }


def build_confirm_requirements_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": CONFIRM_REQUIREMENTS_TOOL_NAME,
            "description": CONFIRM_REQUIREMENTS_DESCRIPTION,
            "parameters": {
                "type": "object",
                "required": [
                    "summary",
                    "key_decisions",
                    "input_description",
                    "output_description",
                ],
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "One paragraph summary of what the user wants to build.",
                    },
                    "key_decisions": {
                        "type": "array",
                        "description": "Key architectural/design decisions derived from discovery.",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["topic", "decision"],
                            "properties": {
                                "topic": {
                                    "type": "string",
                                    "description": "The topic of the decision (e.g. 'Input format').",
                                },
                                "decision": {
                                    "type": "string",
                                    "description": "The chosen option or interpretation.",
                                },
                            },
                        },
                    },
                    "input_description": {
                        "type": "string",
                        "description": "What the user will provide as input when running the flow.",
                    },
                    "output_description": {
                        "type": "string",
                        "description": "What the flow will produce as final output.",
                    },
                    "manual_setup_notes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Things the user needs to do manually after creation "
                            "(e.g. connect knowledge bases, upload DOCX templates)."
                        ),
                    },
                    "assumptions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Safe assumptions the backend or planner made to avoid unnecessary "
                            "questions. Keep them short and user-correctable."
                        ),
                    },
                },
            },
        },
    }


def build_all_tool_schemas(
    available_models: list[dict[str, Any]] | None = None,
    available_kbs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return [
        build_outline_flow_tool_schema(),
        build_ask_structured_question_tool_schema(),
        build_confirm_requirements_tool_schema(),
    ]


def build_discovery_complete_tool_schemas() -> list[dict[str, Any]]:
    return [build_confirm_requirements_tool_schema()]


def build_free_discovery_tool_schemas() -> list[dict[str, Any]]:
    return [build_ask_structured_question_tool_schema()]


__all__ = [
    "ASK_STRUCTURED_QUESTION_DESCRIPTION",
    "ASK_STRUCTURED_QUESTION_TOOL_NAME",
    "CONFIRM_REQUIREMENTS_DESCRIPTION",
    "CONFIRM_REQUIREMENTS_TOOL_NAME",
    "OUTLINE_FLOW_TOOL_NAME",
    "build_all_tool_schemas",
    "build_ask_structured_question_tool_schema",
    "build_confirm_requirements_tool_schema",
    "build_outline_flow_tool_schema",
    "build_discovery_complete_tool_schemas",
    "build_free_discovery_tool_schemas",
    "extract_assumptions",
    "extract_plan_rationale",
    "extract_reasoning",
    "parse_confirm_requirements",
    "parse_outline_flow_arguments",
    "parse_structured_question",
]
