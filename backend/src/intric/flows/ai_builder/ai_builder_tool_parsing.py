from __future__ import annotations

from typing import Any, cast

from intric.flows.ai_builder.ai_builder_framework_policy import (
    is_supported_structured_question_id,
)


def extract_assumptions(arguments: dict[str, Any]) -> list[str]:
    raw = arguments.get("assumptions")
    if isinstance(raw, list):
        return [item for item in cast(list[Any], raw) if isinstance(item, str)]
    return []


def extract_reasoning(arguments: dict[str, Any]) -> str | None:
    raw = arguments.get("reasoning")
    return str(raw) if isinstance(raw, str) and raw else None


def extract_plan_rationale(arguments: dict[str, Any]) -> str | None:
    raw = arguments.get("plan_rationale")
    return str(raw) if isinstance(raw, str) and raw else None


def parse_structured_question(arguments: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate ask_structured_question arguments."""
    question_id = arguments.get("question_id")
    if not isinstance(question_id, str) or not question_id.strip():
        raise ValueError("question_id must be a non-empty string")
    if not is_supported_structured_question_id(question_id):
        raise ValueError(
            "question_id must be one of the supported canonical AI Builder ids"
        )

    question = arguments.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")

    options = arguments.get("options")
    if not isinstance(options, list):
        raise ValueError("options must be a list with at least 2 items")
    options_list = cast(list[Any], options)
    if len(options_list) < 2:
        raise ValueError("options must be a list with at least 2 items")

    cleaned_options: list[dict[str, Any]] = []
    for opt in options_list:
        if not isinstance(opt, dict):
            raise ValueError("each option must have a string 'label'")
        option_dict = cast(dict[str, Any], opt)
        if not isinstance(option_dict.get("label"), str):
            raise ValueError("each option must have a string 'label'")
        cleaned_options.append(
            {
                "id": option_dict.get("id"),
                "label": option_dict["label"],
                "value": option_dict.get("value"),
                "description": option_dict.get("description"),
            }
        )

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


def parse_confirm_requirements(arguments: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate confirm_requirements arguments."""
    summary = arguments.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("summary must be a non-empty string")

    key_decisions = arguments.get("key_decisions")
    if not isinstance(key_decisions, list):
        raise ValueError("key_decisions must be a list with at least 1 item")
    decisions_list = cast(list[Any], key_decisions)
    if len(decisions_list) < 1:
        raise ValueError("key_decisions must be a list with at least 1 item")

    cleaned_decisions: list[dict[str, str]] = []
    for decision in decisions_list:
        if not isinstance(decision, dict):
            raise ValueError("each key_decision must be an object")
        decision_dict = cast(dict[str, Any], decision)
        topic = decision_dict.get("topic")
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("each key_decision must have a non-empty string 'topic'")
        dec_value = decision_dict.get("decision")
        if not isinstance(dec_value, str) or not dec_value.strip():
            raise ValueError(
                "each key_decision must have a non-empty string 'decision'"
            )
        cleaned_decisions.append(
            {
                "topic": topic.strip(),
                "decision": dec_value.strip(),
            }
        )

    input_description = arguments.get("input_description")
    if not isinstance(input_description, str) or not input_description.strip():
        raise ValueError("input_description must be a non-empty string")

    output_description = arguments.get("output_description")
    if not isinstance(output_description, str) or not output_description.strip():
        raise ValueError("output_description must be a non-empty string")

    raw_notes = arguments.get("manual_setup_notes")
    manual_setup_notes: list[str] = []
    if isinstance(raw_notes, list):
        manual_setup_notes = [
            note for note in cast(list[Any], raw_notes) if isinstance(note, str)
        ]

    raw_assumptions = arguments.get("assumptions")
    assumptions: list[str] = []
    if isinstance(raw_assumptions, list):
        assumptions = [
            str(item).strip()
            for item in cast(list[Any], raw_assumptions)
            if isinstance(item, str) and str(item).strip()
        ]

    return {
        "summary": summary.strip(),
        "key_decisions": cleaned_decisions,
        "input_description": input_description.strip(),
        "output_description": output_description.strip(),
        "assumptions": assumptions,
        "manual_setup_notes": manual_setup_notes,
    }
