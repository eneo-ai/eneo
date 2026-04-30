"""Deterministic server-owned planner actions.

This is the state-machine seam that removes phase-control decisions from
the LLM. The model may still generate rich semantic content later, but
basic discovery and architecture transitions are server decisions based
on `PlanningState` and `PlannerActionPolicy`.
"""

from __future__ import annotations

from collections.abc import Mapping

from intric.flows.ai_builder.ai_builder_action_policy import PlannerActionPolicy
from intric.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from intric.flows.ai_builder.ai_builder_event_models import KeyDecisionPayload
from intric.flows.ai_builder.ai_builder_orchestrator import (
    AskQuestionAction,
    AskQuestionPayload,
    CommitArchitectureAction,
    CommitArchitecturePayload,
    ConfirmRequirementsAction,
    ConfirmRequirementsPayload,
    PlannerOutput,
    PlanningStateDelta,
)
from intric.flows.ai_builder.planning_state import PlanningState
from intric.flows.ai_builder.question_catalog import Locale, render_question


def build_server_planner_output(
    *,
    action_policy: PlannerActionPolicy,
    session_state: PlanningState,
    base_planning_state_version: int,
    ui_language: str | None,
) -> PlannerOutput | None:
    """Return a deterministic planner output when the server can decide.

    Ordering is deliberate: if there is an allowed question target, the
    server asks it without making the LLM choose the identifier. If no
    questions remain and commit is legal, the server commits the derived
    architecture. Plan proposal uses a separate task-specific LLM
    boundary because its content is semantic and much larger than the
    phase transition.
    """

    if "ask_question" in action_policy.allowed_action_kinds:
        target = _first(action_policy.allowed_ask_question_targets)
        if target is not None:
            return _ask_question_output(
                base_planning_state_version=base_planning_state_version,
                target=target,
                ui_language=ui_language,
            )

    if (
        "commit_architecture" in action_policy.allowed_action_kinds
        and session_state.architecture_commit is None
    ):
        draft = derive_architecture_commit_draft(session_state)
        if draft is not None:
            return PlannerOutput(
                planning_state_delta=PlanningStateDelta(
                    base_planning_state_version=base_planning_state_version,
                    architecture_commit=draft,
                ),
                planner_action=CommitArchitectureAction(
                    kind="commit_architecture",
                    payload=CommitArchitecturePayload(
                        note="Architecture committed from resolved planning state."
                    ),
                ),
            )

    if "confirm_requirements" in action_policy.allowed_action_kinds:
        return _confirm_requirements_output(
            base_planning_state_version=base_planning_state_version,
            session_state=session_state,
            ui_language=ui_language,
        )

    return None


def _ask_question_output(
    *,
    base_planning_state_version: int,
    target: str,
    ui_language: str | None,
) -> PlannerOutput:
    return PlannerOutput(
        planning_state_delta=PlanningStateDelta(
            base_planning_state_version=base_planning_state_version,
        ),
        planner_action=AskQuestionAction(
            kind="ask_question",
            payload=AskQuestionPayload(
                question_id=target,
                slot_name=target,
                prompt=_question_prompt(target, ui_language),
            ),
        ),
    )


def _question_prompt(target: str, ui_language: str | None) -> str:
    rendered = render_question(target, _locale(ui_language))
    option_lines = "\n".join(
        f"- {option.label}: {option.description}" for option in rendered.options
    )
    if not option_lines:
        return rendered.question
    return f"{rendered.question}\n\n{option_lines}"


def _locale(ui_language: str | None) -> Locale:
    return "sv" if ui_language == "sv" else "en"


def _confirm_requirements_output(
    *,
    base_planning_state_version: int,
    session_state: PlanningState,
    ui_language: str | None,
) -> PlannerOutput:
    return PlannerOutput(
        planning_state_delta=PlanningStateDelta(
            base_planning_state_version=base_planning_state_version,
        ),
        planner_action=ConfirmRequirementsAction(
            kind="confirm_requirements",
            payload=build_confirm_requirements_payload_from_state(
                session_state,
                ui_language,
            ),
        ),
    )


def build_confirm_requirements_payload_from_state(
    session_state: PlanningState,
    ui_language: str | None,
) -> ConfirmRequirementsPayload:
    return _confirm_requirements_payload(session_state, _locale(ui_language))


def _confirm_requirements_payload(
    session_state: PlanningState,
    locale: Locale,
) -> ConfirmRequirementsPayload:
    resolved = session_state.resolved_slots
    key_decisions = [
        KeyDecisionPayload(
            topic=_slot_label(slot_name, locale),
            decision=_slot_value_for_slot(
                slot_name,
                resolved[slot_name].value,
                locale,
            ),
        )
        for slot_name in sorted(resolved)
    ]
    input_description = _input_description(resolved, locale)
    output_description = _output_description(resolved, locale)
    return ConfirmRequirementsPayload(
        summary=_summary_text(resolved, locale),
        key_decisions=key_decisions,
        input_description=input_description,
        output_description=output_description,
        assumptions=_assumptions(locale),
        manual_setup_notes=[],
    )


def _summary_text(
    resolved: Mapping[str, object],
    locale: Locale,
) -> str:
    runtime_input = _slot_value_for_slot(
        "primary_runtime_input",
        _resolved_value(resolved, "primary_runtime_input"),
        locale,
    )
    terminal_output = _slot_value_for_slot(
        "terminal_output",
        _resolved_value(resolved, "terminal_output"),
        locale,
    )
    analysis_need = _slot_value_for_slot(
        "structured_analysis_need",
        _resolved_value(resolved, "structured_analysis_need"),
        locale,
    )
    if runtime_input or terminal_output:
        if locale == "sv":
            summary = (
                f"Flödet ska ta emot {runtime_input or 'indata'} vid körning "
                f"och leverera {terminal_output or 'ett slutresultat'}."
            )
            if analysis_need:
                summary += f" Analysen ska stödja: {analysis_need}."
            return summary
        summary = (
            f"The flow should accept {runtime_input or 'runtime input'} "
            f"and deliver {terminal_output or 'a final result'}."
        )
        if analysis_need:
            summary += f" The analysis should support: {analysis_need}."
        return summary

    if locale == "sv":
        return (
            "Jag har tillräckligt med information för att ta fram ett "
            "förslag till flödesplan. Granska sammanfattningen innan planen "
            "byggs."
        )
    return (
        "I have enough information to draft a flow plan. Review this "
        "summary before the plan is built."
    )


def _input_description(
    resolved: Mapping[str, object],
    locale: Locale,
) -> str:
    value = _resolved_value(resolved, "primary_runtime_input")
    rendered_value = _slot_value_for_slot("primary_runtime_input", value, locale)
    if locale == "sv":
        return (
            f"Primär indata vid körning: {rendered_value}."
            if value
            else "Primär indata vid körning behöver granskas."
        )
    return (
        f"Primary runtime input: {rendered_value}."
        if value
        else "Primary runtime input needs review."
    )


def _output_description(
    resolved: Mapping[str, object],
    locale: Locale,
) -> str:
    value = _resolved_value(resolved, "terminal_output")
    rendered_value = _slot_value_for_slot("terminal_output", value, locale)
    if locale == "sv":
        return (
            f"Huvudsakligt slutresultat: {rendered_value}."
            if value
            else "Huvudsakligt slutresultat behöver granskas."
        )
    return (
        f"Primary final output: {rendered_value}."
        if value
        else "Primary final output needs review."
    )


def _assumptions(locale: Locale) -> list[str]:
    if locale == "sv":
        return [
            "Planen ska följa kraven och underlaget i konversationen.",
            "Användaren ska kunna granska och ändra planen innan den tillämpas.",
        ]
    return [
        "The plan should follow the requirements and source material in the conversation.",
        "The user can review and change the plan before it is applied.",
    ]


def _resolved_value(resolved: Mapping[str, object], slot_name: str) -> str:
    slot = resolved.get(slot_name)
    value = getattr(slot, "value", "")
    return value if isinstance(value, str) else ""


def _slot_label(slot_name: str, locale: Locale) -> str:
    labels_sv = {
        "primary_runtime_input": "Indata vid körning",
        "terminal_output": "Slutresultat",
        "document_material_scope": "Dokumentunderlag",
        "runtime_metadata_fields": "Metadata vid körning",
        "docx_output_mode": "DOCX-resultat",
        "pdf_generation_mode": "PDF-resultat",
        "structured_analysis_need": "Strukturerad analys",
    }
    labels_en = {
        "primary_runtime_input": "Runtime input",
        "terminal_output": "Final output",
        "document_material_scope": "Document source material",
        "runtime_metadata_fields": "Runtime metadata",
        "docx_output_mode": "DOCX output",
        "pdf_generation_mode": "PDF output",
        "structured_analysis_need": "Structured analysis",
    }
    labels = labels_sv if locale == "sv" else labels_en
    return labels.get(slot_name, slot_name.replace("_", " ").title())


def _slot_value(value: str) -> str:
    return value.replace("_", " ")


def _slot_value_for_slot(slot_name: str, value: str, locale: Locale) -> str:
    try:
        rendered = render_question(slot_name, locale)
    except KeyError:
        return _slot_value(value)

    for option in rendered.options:
        if value in {option.value, option.id}:
            return option.label
    return _slot_value(value)


def _first(values: tuple[str, ...]) -> str | None:
    return values[0] if values else None


__all__ = ["build_server_planner_output"]
