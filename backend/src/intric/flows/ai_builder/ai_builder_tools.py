"""Tool schemas for the AI Flow Builder.

Defines the `propose_flow`, `validate_flow_draft`, and `ask_structured_question` tools that
the LLM calls during the flow design conversation.
"""

from __future__ import annotations

from typing import Any

from intric.flows.ai_builder.ai_builder_models import (
    FlowDraftSpecCore,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    is_supported_structured_question_id,
    supported_structured_question_ids,
)
from intric.flows.ai_builder.ai_builder_runtime_input_defaults import (
    normalize_builder_draft_runtime_inputs,
)

# ---------------------------------------------------------------------------
# Tool definition for LLM consumption (JSON Schema)
# ---------------------------------------------------------------------------

PROPOSE_FLOW_TOOL_NAME = "propose_flow"

PROPOSE_FLOW_TOOL_DESCRIPTION = (
    "Submit a complete flow definition for validation and user approval. "
    "The plan will be validated and presented to the user as a visual plan card. "
    "The user must approve before any changes are made. "
    "Always call this tool to present your plan — never just describe it in text."
)

VALIDATE_FLOW_DRAFT_TOOL_NAME = "validate_flow_draft"

VALIDATE_FLOW_DRAFT_TOOL_DESCRIPTION = (
    "Validate a draft flow before you submit it. "
    "Use this when the draft contains contracts, variable bindings, template_fill, "
    "or any non-trivial chaining. Inspect the returned validation result, fix hard "
    "errors, and only then call propose_flow."
)

MAX_FLOW_STEPS = 12


def build_propose_flow_tool_schema() -> dict[str, Any]:
    """Build the JSON Schema tool definition for propose_flow.

    Uses standard JSON Schema so it works with any LLM provider
    that supports tool calling (OpenAI, Anthropic, Google, etc.).
    """
    return {
        "type": "function",
        "function": {
            "name": PROPOSE_FLOW_TOOL_NAME,
            "description": PROPOSE_FLOW_TOOL_DESCRIPTION,
            "parameters": _build_parameters_schema(),
        },
    }


def build_validate_flow_draft_tool_schema() -> dict[str, Any]:
    """Build the JSON Schema tool definition for validate_flow_draft."""
    return {
        "type": "function",
        "function": {
            "name": VALIDATE_FLOW_DRAFT_TOOL_NAME,
            "description": VALIDATE_FLOW_DRAFT_TOOL_DESCRIPTION,
            "parameters": _build_parameters_schema(),
        },
    }


def parse_propose_flow_arguments(arguments: dict[str, Any]) -> FlowDraftSpecCore:
    """Parse and validate raw tool call arguments into FlowDraftSpecCore.

    The `assumptions` and `reasoning` fields are extracted separately by the
    caller since they belong to PlannerPlanEnvelope, not the core spec.
    """
    arguments = _unwrap_spec_payload(arguments)

    # Strip non-spec fields before validation
    cleaned = {
        k: v
        for k, v in arguments.items()
        if k not in ("assumptions", "reasoning", "plan_rationale")
    }
    return normalize_builder_draft_runtime_inputs(FlowDraftSpecCore.model_validate(cleaned))


def extract_assumptions(arguments: dict[str, Any]) -> list[str]:
    """Extract assumptions from raw tool call arguments."""
    raw = arguments.get("assumptions")
    if isinstance(raw, list):
        return [str(item) for item in raw if isinstance(item, str)]
    return []


def extract_reasoning(arguments: dict[str, Any]) -> str | None:
    """Extract the chain-of-thought reasoning from raw tool call arguments."""
    raw = arguments.get("reasoning")
    return str(raw) if isinstance(raw, str) and raw else None


def extract_plan_rationale(arguments: dict[str, Any]) -> str | None:
    """Extract the short user-visible planning rationale from raw tool call arguments."""
    raw = arguments.get("plan_rationale")
    return str(raw) if isinstance(raw, str) and raw else None


# ---------------------------------------------------------------------------
# ask_structured_question tool
# ---------------------------------------------------------------------------

ASK_STRUCTURED_QUESTION_TOOL_NAME = "ask_structured_question"

ASK_STRUCTURED_QUESTION_DESCRIPTION = (
    "Ask the user a question with clickable options instead of free text. "
    "Use only for backend-supported canonical discovery questions. "
    "Do not invent new question ids, custom option families, or ad hoc discovery branches."
)


def build_ask_structured_question_tool_schema() -> dict[str, Any]:
    """Build the JSON Schema tool definition for ask_structured_question."""
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


def parse_structured_question(arguments: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate ask_structured_question arguments.

    Returns a cleaned dict with question, options, selection_mode, allow_custom.
    """
    question_id = arguments.get("question_id")
    if not isinstance(question_id, str) or not question_id.strip():
        raise ValueError("question_id must be a non-empty string")
    if not is_supported_structured_question_id(question_id):
        raise ValueError("question_id must be one of the supported canonical AI Builder ids")

    question = arguments.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")

    options = arguments.get("options")
    if not isinstance(options, list) or len(options) < 2:
        raise ValueError("options must be a list with at least 2 items")

    cleaned_options = []
    for opt in options:
        if not isinstance(opt, dict) or not isinstance(opt.get("label"), str):
            raise ValueError("each option must have a string 'label'")
        cleaned_options.append({
            "id": opt.get("id"),
            "label": opt["label"],
            "value": opt.get("value"),
            "description": opt.get("description"),
        })

    selection_mode = arguments.get("selection_mode", "single")
    if selection_mode not in {"single", "multi"}:
        raise ValueError("selection_mode must be 'single' or 'multi'")

    allow_custom = arguments.get("allow_custom", True)
    if not isinstance(allow_custom, bool):
        raise ValueError("allow_custom must be boolean")

    return {
        "question_id": question_id.strip(),
        "question": question.strip(),
        "options": cleaned_options,
        "selection_mode": selection_mode,
        "allow_custom": allow_custom,
    }


# ---------------------------------------------------------------------------
# confirm_requirements tool
# ---------------------------------------------------------------------------

CONFIRM_REQUIREMENTS_TOOL_NAME = "confirm_requirements"

CONFIRM_REQUIREMENTS_DESCRIPTION = (
    "Present your understanding of the user's needs for confirmation before building a plan. "
    "Call this after discovery to summarize what you understood. "
    "The user must confirm before you call propose_flow."
)


def build_confirm_requirements_tool_schema() -> dict[str, Any]:
    """Build the JSON Schema tool definition for confirm_requirements."""
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


def parse_confirm_requirements(arguments: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate confirm_requirements arguments.

    Returns a cleaned dict with summary, key_decisions, input/output descriptions,
    and manual_setup_notes.
    """
    summary = arguments.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("summary must be a non-empty string")

    key_decisions = arguments.get("key_decisions")
    if not isinstance(key_decisions, list) or len(key_decisions) < 1:
        raise ValueError("key_decisions must be a list with at least 1 item")

    cleaned_decisions = []
    for decision in key_decisions:
        if not isinstance(decision, dict):
            raise ValueError("each key_decision must be an object")
        topic = decision.get("topic")
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("each key_decision must have a non-empty string 'topic'")
        dec_value = decision.get("decision")
        if not isinstance(dec_value, str) or not dec_value.strip():
            raise ValueError("each key_decision must have a non-empty string 'decision'")
        cleaned_decisions.append({
            "topic": topic.strip(),
            "decision": dec_value.strip(),
        })

    input_description = arguments.get("input_description")
    if not isinstance(input_description, str) or not input_description.strip():
        raise ValueError("input_description must be a non-empty string")

    output_description = arguments.get("output_description")
    if not isinstance(output_description, str) or not output_description.strip():
        raise ValueError("output_description must be a non-empty string")

    raw_notes = arguments.get("manual_setup_notes")
    manual_setup_notes: list[str] = []
    if isinstance(raw_notes, list):
        manual_setup_notes = [str(note) for note in raw_notes if isinstance(note, str)]

    raw_assumptions = arguments.get("assumptions")
    assumptions: list[str] = []
    if isinstance(raw_assumptions, list):
        assumptions = [str(item).strip() for item in raw_assumptions if isinstance(item, str) and str(item).strip()]

    return {
        "summary": summary.strip(),
        "key_decisions": cleaned_decisions,
        "input_description": input_description.strip(),
        "output_description": output_description.strip(),
        "assumptions": assumptions,
        "manual_setup_notes": manual_setup_notes,
    }


# ---------------------------------------------------------------------------
# All tools helper
# ---------------------------------------------------------------------------


def build_all_tool_schemas() -> list[dict[str, Any]]:
    """Build all tool schemas for the AI builder LLM call."""
    return [
        build_propose_flow_tool_schema(),
        build_ask_structured_question_tool_schema(),
        build_confirm_requirements_tool_schema(),
    ]


def build_discovery_complete_tool_schemas() -> list[dict[str, Any]]:
    """Build the reduced tool set for the phase after discovery but before confirmation.

    At this point the backend owns discovery state and the model should only
    summarize understood requirements for user confirmation.
    """
    return [build_confirm_requirements_tool_schema()]


def build_free_discovery_tool_schemas() -> list[dict[str, Any]]:
    """Build tools for free discovery mode (MVS not yet met).

    Only ask_structured_question is available — no confirm or propose.
    The LLM can chat freely in text AND use structured questions.
    """
    return [build_ask_structured_question_tool_schema()]


# ---------------------------------------------------------------------------
# Internal schema builders
# ---------------------------------------------------------------------------


def _build_parameters_schema() -> dict[str, Any]:
    """Build the JSON Schema for propose_flow parameters."""
    return {
        "type": "object",
        "required": ["flow_name", "steps"],
        "properties": {
            "reasoning": {
                "type": "string",
                "description": (
                    "Think step-by-step before generating the flow. "
                    "Consider: what data flows between steps, which variables connect them, "
                    "which steps need output_contracts for downstream structured access, "
                    "and what the user's core intent is. This field is not shown to the user."
                ),
            },
            "flow_name": {
                "type": "string",
                "minLength": 1,
                "description": "Name of the flow.",
            },
            "flow_description": {
                "type": "string",
                "description": "Short description of what the flow does.",
                "default": "",
            },
            "plan_rationale": {
                "type": "string",
                "description": (
                    "Short user-visible explanation of why this flow shape was chosen. "
                    "Mention key design decisions like JSON extraction, contracts, or template_fill."
                ),
            },
            "steps": {
                "type": "array",
                "description": "Ordered list of flow steps.",
                "items": _step_spec_schema(),
                "minItems": 1,
                "maxItems": MAX_FLOW_STEPS,
            },
            "form_fields": {
                "type": "array",
                "description": "Optional form fields for structured runtime input.",
                "items": _form_field_schema(),
            },
            "assumptions": {
                "type": "array",
                "description": (
                    "Assumptions you are making about the user's intent. "
                    "These are shown to the user for transparency."
                ),
                "items": {"type": "string"},
            },
        },
    }


def _step_spec_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["plan_step_ref", "name", "assistant_spec", "input_source"],
        "properties": {
            "plan_step_ref": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Stable reference for this step (e.g. 'step_a', 'step_b'). "
                    "Used in variable bindings like {{ step_a.output.text }}. "
                    "Reuse the exact declared ref in all bindings and instructions. "
                    "Do not use runtime refs like step_1 or user_description aliases in drafts."
                ),
            },
            "existing_step_ref": {
                "type": "string",
                "description": (
                    "Server-provided alias for an existing step when modifying. "
                    "Only set for steps that already exist in the flow."
                ),
            },
            "name": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "User-visible step name. Use descriptive Swedish names. "
                    "This label is not the canonical variable reference; use plan_step_ref for bindings."
                ),
            },
            "assistant_spec": _assistant_spec_schema(),
            "mcp_policy": {
                "type": "string",
                "enum": [e.value for e in MCPPolicy],
                "default": MCPPolicy.INHERIT.value,
                "description": "MCP tool policy for this step.",
            },
            "input_source": {
                "type": "string",
                "enum": [e.value for e in InputSource],
                "description": (
                    "Where this step gets its input. "
                    "Step 1 must use 'flow_input'. "
                    "Later steps use 'previous_step' or 'all_previous_steps'."
                ),
            },
            "input_type": {
                "type": "string",
                "enum": [e.value for e in InputType],
                "default": InputType.TEXT.value,
                "description": (
                    "Type of input data. 'audio', 'document', and 'file' "
                    "are only valid with input_source 'flow_input'."
                ),
            },
            "output_mode": {
                "type": "string",
                "enum": [e.value for e in OutputMode],
                "default": OutputMode.PASS_THROUGH.value,
                "description": (
                    "How the step processes output. "
                    "'transcribe_only' requires audio input. "
                    "'template_fill' requires docx output."
                ),
            },
            "output_type": {
                "type": "string",
                "enum": [e.value for e in OutputType],
                "default": OutputType.TEXT.value,
                "description": "Type of output data.",
            },
            "input_bindings": {
                "type": "object",
                "description": (
                    "Variable bindings for step input. Primary key: 'question'. "
                    "Use the exact plan_step_ref values declared in steps[*].plan_step_ref. "
                    "Prefer {{ step_a.output.structured.field }} for JSON-producing steps, "
                    "{{ step_a.output.text }} for text output, {{ FieldName }} for form fields, "
                    "and {{ step_input.text }} when runtime_input is enabled and you need uploaded "
                    "runtime material in an explicit question. Structure with UPPERCASE HEADERS for clarity."
                ),
                "required": ["question"],
                "additionalProperties": False,
                "properties": {
                    "question": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "The assembled step input text. Use variables like "
                            "{{ step_a.output.text }} and {{ Ärendenummer }}. "
                            "When runtime_input is enabled and question is present, include a real "
                            "{{ step_input.* }} reference. Prefer specific output.structured fields over "
                            "raw output.text blobs from JSON-producing steps."
                        ),
                    }
                },
            },
            "input_contract": {
                "type": "object",
                "description": (
                    "JSON Schema (Draft 2020-12) for input validation. "
                    "Only valid for input_type 'text' or 'json'. "
                    "Use 'description' on fields for the variable picker. "
                    "Write descriptions in Swedish."
                ),
            },
            "output_contract": {
                "type": "object",
                "description": (
                    "JSON Schema (Draft 2020-12) for output validation. "
                    "STRONGLY RECOMMENDED for output_type 'json' — enables "
                    "downstream steps to reference specific fields via "
                    "{{ step_X.output.structured.field }}. "
                    "Include 'description' on each field. Write in Swedish."
                ),
            },
            "input_config": {
                "type": "object",
                "description": (
                    "Additional input configuration. For flow_input steps with input_type "
                    "document/file/audio, set input_config.runtime_input.enabled=true to use "
                    "the 'Ta emot filer vid körning' upload area in the run dialog. "
                    "If input_bindings.question is also present, it must consume runtime input via "
                    "{{ step_input.text }} or another real step_input.* reference."
                ),
            },
            "output_config": {
                "type": "object",
                "description": "Additional output configuration (e.g. template_fill bindings).",
            },
        },
    }


def _assistant_spec_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["instructions"],
        "description": "Inline assistant definition for this step.",
        "properties": {
            "instructions": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "The prompt/instructions for this step's assistant. "
                    "Be concise and specific. Use Swedish unless user writes in English."
                ),
            },
            "model_ref": {
                "type": "string",
                "description": (
                    "Server-provided model alias, or null for the space default model."
                ),
            },
            "knowledge_refs": {
                "type": "array",
                "items": {"type": "string"},
                "uniqueItems": True,
                "description": "Server-provided knowledge base aliases to attach.",
            },
        },
    }


def _form_field_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["name", "type", "label"],
        "properties": {
            "name": {
                "type": "string",
                "description": "Field identifier (used in variable bindings).",
            },
            "type": {
                "type": "string",
                "enum": ["text", "number", "date", "select", "multiselect"],
                "description": "Field type.",
            },
            "label": {
                "type": "string",
                "description": "User-visible label.",
            },
            "required": {
                "type": "boolean",
                "default": False,
                "description": "Whether the field is required.",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Options for select/multiselect fields.",
            },
        },
    }


def _unwrap_spec_payload(arguments: dict[str, Any]) -> dict[str, Any]:
    """Accept common nested wrapper shapes some models use around flow drafts."""
    for key in ("spec", "draft", "flow"):
        candidate = arguments.get(key)
        if (
            isinstance(candidate, dict)
            and "flow_name" in candidate
            and ("steps" in candidate or "form_fields" in candidate)
        ):
            return candidate
    return arguments
