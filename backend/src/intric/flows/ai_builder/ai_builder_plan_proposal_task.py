"""Task-specific prompt for final AI Builder plan proposal.

This prompt is intentionally not the planner union contract. The server
has already selected the phase; the model only drafts semantic flow
content through the create/edit tool schema.
"""

from __future__ import annotations

from typing import Any, cast

from intric.flows.ai_builder.planning_state import PlanningState


def build_plan_proposal_system_prompt(
    *,
    planning_state: PlanningState,
    confirmed_requirements: dict[str, Any] | None,
    attachment_context: str | None,
    flow_context: str | None,
    is_edit_mode: bool,
) -> str:
    """Build a compact task prompt for create/edit flow proposal."""

    submission_tool = "edit_flow" if is_edit_mode else "outline_flow"
    create_mode_rules = (
        [
            "- In create mode, describe semantic flow intent in outline_flow; do not choose Flow mechanics.",
            "- Use input_fields only for secondary inmatningsfält/input variables the user fills in at runtime.",
            "- Do not add an input_field for the primary text, document, file, or audio material being processed; the backend supplies that from the committed architecture.",
            "- The backend compiles step topology, underlag/input_bindings, runtime uploads, step refs, output modes, and document delivery.",
        ]
        if not is_edit_mode
        else []
    )
    lines = [
        "You are drafting an Eneo Flow plan.",
        "",
        "The backend has already completed discovery and selected this turn's phase.",
        f"Call exactly one `{submission_tool}` tool. Do not ask a question, do not confirm requirements, and do not return prose only.",
        "",
        "Design rules:",
        "- Use as many steps as the requested workflow needs, up to the tool schema limit.",
        "- Prefer a clear multi-step flow for complex work instead of one overloaded step.",
        "- Use JSON output fields when later steps need specific structured facts.",
        "- Describe each step's semantic work; the backend derives runtime uploads and final output mechanics from the committed architecture.",
        "- Do not author field-level previous-step paths; let the backend wire dataflow.",
        "- Do not write template variables, raw JSON Schema, raw input bindings, IDs, hashes, timestamps, or backend-owned refs.",
        "- The backend will compile, validate, and persist the plan for user approval.",
        *create_mode_rules,
        "",
        "Committed architecture:",
        _architecture_block(planning_state),
        "",
        "Resolved planning slots:",
        _resolved_slots_block(planning_state),
        "",
        "Confirmed requirements:",
        _confirmed_requirements_block(confirmed_requirements),
    ]
    if flow_context:
        lines.extend(["", "Existing flow context:", flow_context])
    if attachment_context:
        lines.extend(["", "Attachment context:", attachment_context])
    return "\n".join(lines)


def _architecture_block(planning_state: PlanningState) -> str:
    commit = planning_state.architecture_commit
    if commit is None:
        return "- No committed architecture is present. Create the safest valid plan."
    tuples = [
        f"- {triple.input_type} -> {triple.output_type} ({triple.output_mode})"
        for triple in commit.tuples_chain
    ]
    patterns = ", ".join(commit.chosen_patterns) or "none"
    capabilities = ", ".join(commit.required_capabilities) or "none"
    return "\n".join(
        [
            *tuples,
            f"- chosen_patterns: {patterns}",
            f"- required_capabilities: {capabilities}",
        ]
    )


def _resolved_slots_block(planning_state: PlanningState) -> str:
    if not planning_state.resolved_slots:
        return "- none"
    return "\n".join(
        f"- {name}: {slot.value}"
        for name, slot in sorted(planning_state.resolved_slots.items())
    )


def _confirmed_requirements_block(
    confirmed_requirements: dict[str, Any] | None,
) -> str:
    if not confirmed_requirements:
        return "- none"

    lines: list[str] = []
    for key in (
        "summary",
        "input_description",
        "output_description",
    ):
        value = confirmed_requirements.get(key)
        if isinstance(value, str) and value.strip():
            lines.append(f"- {key}: {value.strip()}")

    key_decisions = confirmed_requirements.get("key_decisions")
    if isinstance(key_decisions, list) and key_decisions:
        lines.append("- key_decisions:")
        for raw_decision in cast(list[Any], key_decisions):
            if not isinstance(raw_decision, dict):
                continue
            decision = cast(dict[str, Any], raw_decision)
            topic = decision.get("topic")
            selected = decision.get("decision")
            if isinstance(topic, str) and isinstance(selected, str):
                lines.append(f"  - {topic}: {selected}")

    assumptions = confirmed_requirements.get("assumptions")
    if isinstance(assumptions, list) and assumptions:
        lines.append("- assumptions:")
        for assumption in cast(list[Any], assumptions):
            if isinstance(assumption, str) and assumption.strip():
                lines.append(f"  - {assumption.strip()}")

    return "\n".join(lines) if lines else "- none"


__all__ = ["build_plan_proposal_system_prompt"]
