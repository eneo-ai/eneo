"""Deterministic server-owned Builder turn control.

The model may still generate rich semantic proposal content, but discovery,
architecture commitment, requirements confirmation, and proposal phase
selection are server decisions derived from typed `PlanningState`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeAlias

from eneo.flows.ai_builder.ai_builder_action_policy import (
    PlannerActionPolicy,
    build_planner_action_policy,
    compute_unresolved_core_slots,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    KeyDecisionPayload,
    RequirementsSummaryPayload,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import (
    DEFAULT_FINAL_OUTPUT_NEEDS_REVIEW_EN,
    DEFAULT_FINAL_OUTPUT_NEEDS_REVIEW_SV,
    DEFAULT_PLAN_FOLLOWS_REQUIREMENTS_EN,
    DEFAULT_PLAN_FOLLOWS_REQUIREMENTS_SV,
    DEFAULT_REQUIREMENTS_SUMMARY_EN,
    DEFAULT_REQUIREMENTS_SUMMARY_SV,
    DEFAULT_RUNTIME_INPUT_NEEDS_REVIEW_EN,
    DEFAULT_RUNTIME_INPUT_NEEDS_REVIEW_SV,
    DEFAULT_USER_REVIEWS_PLAN_EN,
    DEFAULT_USER_REVIEWS_PLAN_SV,
)
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommitDraft,
    PlanningState,
)
from eneo.flows.ai_builder.question_catalog import Locale, render_question


@dataclass(frozen=True, slots=True)
class AskCanonicalQuestion:
    slot_name: str
    prompt: str


@dataclass(frozen=True, slots=True)
class CommitArchitecture:
    architecture_commit: ArchitectureCommitDraft


@dataclass(frozen=True, slots=True)
class ConfirmRequirements:
    payload: RequirementsSummaryPayload


@dataclass(frozen=True, slots=True)
class GenerateProposal:
    is_edit_mode: bool


BuilderTurnDecision: TypeAlias = (
    AskCanonicalQuestion | CommitArchitecture | ConfirmRequirements | GenerateProposal
)


@dataclass(frozen=True, slots=True)
class BuilderTurnControl:
    decision: BuilderTurnDecision
    action_policy: PlannerActionPolicy
    unresolved_architectural_choices: frozenset[str]


def resolve_turn_control(
    *,
    session_state: PlanningState,
    selected_discovery_question_ids: tuple[str, ...],
    requirements_confirmed: bool,
    is_edit_mode: bool,
    ui_language: str | None,
) -> BuilderTurnControl:
    unresolved_core_slots = compute_unresolved_core_slots(session_state)
    action_policy = build_planner_action_policy(
        session_state=session_state,
        unresolved_architectural_choices=unresolved_core_slots,
        selected_discovery_question_ids=selected_discovery_question_ids,
        requirements_confirmed=requirements_confirmed,
    )
    return BuilderTurnControl(
        decision=_decision_from_policy(
            action_policy=action_policy,
            session_state=session_state,
            is_edit_mode=is_edit_mode,
            ui_language=ui_language,
        ),
        action_policy=action_policy,
        unresolved_architectural_choices=unresolved_core_slots,
    )


def _decision_from_policy(
    *,
    action_policy: PlannerActionPolicy,
    session_state: PlanningState,
    is_edit_mode: bool,
    ui_language: str | None,
) -> BuilderTurnDecision:
    if "ask_question" in action_policy.allowed_action_kinds:
        target = _first(action_policy.allowed_ask_question_targets)
        if target is not None:
            return AskCanonicalQuestion(
                slot_name=target,
                prompt=_question_prompt(target, ui_language),
            )

    if (
        "commit_architecture" in action_policy.allowed_action_kinds
        and session_state.architecture_commit is None
    ):
        draft = derive_architecture_commit_draft(session_state)
        if draft is not None:
            return CommitArchitecture(architecture_commit=draft)

    if "confirm_requirements" in action_policy.allowed_action_kinds:
        return ConfirmRequirements(
            payload=_confirm_requirements_payload(
                session_state,
                _locale(ui_language),
            )
        )

    if action_policy.allowed_action_kinds == ("propose_plan",):
        return GenerateProposal(is_edit_mode=is_edit_mode)

    raise ValueError(
        "No Builder turn decision can be derived from action policy "
        f"{action_policy.allowed_action_kinds!r}"
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


def _confirm_requirements_payload(
    session_state: PlanningState,
    locale: Locale,
) -> RequirementsSummaryPayload:
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
    architecture_decision = _architecture_decision(session_state, locale)
    if architecture_decision is not None:
        key_decisions.append(architecture_decision)
    input_description = _input_description(resolved, locale)
    output_description = _output_description(resolved, locale)
    return RequirementsSummaryPayload(
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
    post_processing_goal = _slot_value_for_slot(
        "post_processing_goal",
        _resolved_value(resolved, "post_processing_goal"),
        locale,
    )
    if runtime_input or terminal_output or post_processing_goal:
        if locale == "sv":
            summary = (
                f"Flödet ska ta emot {runtime_input or 'indata'} vid körning "
                f"och leverera {terminal_output or 'ett slutresultat'}."
            )
            if post_processing_goal:
                summary += f" Resultatet ska hjälpa till med: {post_processing_goal}."
            if analysis_need:
                summary += f" Analysen ska stödja: {analysis_need}."
            return summary
        summary = (
            f"The flow should accept {runtime_input or 'runtime input'} "
            f"and deliver {terminal_output or 'a final result'}."
        )
        if post_processing_goal:
            summary += f" The result should help with: {post_processing_goal}."
        if analysis_need:
            summary += f" The analysis should support: {analysis_need}."
        return summary

    if locale == "sv":
        return DEFAULT_REQUIREMENTS_SUMMARY_SV
    return DEFAULT_REQUIREMENTS_SUMMARY_EN


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
            else DEFAULT_RUNTIME_INPUT_NEEDS_REVIEW_SV
        )
    return (
        f"Primary runtime input: {rendered_value}."
        if value
        else DEFAULT_RUNTIME_INPUT_NEEDS_REVIEW_EN
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
            else DEFAULT_FINAL_OUTPUT_NEEDS_REVIEW_SV
        )
    return (
        f"Primary final output: {rendered_value}."
        if value
        else DEFAULT_FINAL_OUTPUT_NEEDS_REVIEW_EN
    )


def _assumptions(locale: Locale) -> list[str]:
    if locale == "sv":
        return [
            DEFAULT_PLAN_FOLLOWS_REQUIREMENTS_SV,
            DEFAULT_USER_REVIEWS_PLAN_SV,
        ]
    return [
        DEFAULT_PLAN_FOLLOWS_REQUIREMENTS_EN,
        DEFAULT_USER_REVIEWS_PLAN_EN,
    ]


def _architecture_decision(
    session_state: PlanningState,
    locale: Locale,
) -> KeyDecisionPayload | None:
    commit = session_state.architecture_commit
    if commit is None or not commit.tuples_chain:
        return None
    topic = "Planerad bearbetning" if locale == "sv" else "Planned processing"
    steps = [
        _triple_summary(
            input_type=triple.input_type,
            output_type=triple.output_type,
            output_mode=triple.output_mode,
            locale=locale,
        )
        for triple in commit.tuples_chain
    ]
    return KeyDecisionPayload(topic=topic, decision=" → ".join(steps))


def _triple_summary(
    *,
    input_type: str,
    output_type: str,
    output_mode: str,
    locale: Locale,
) -> str:
    if output_mode == "transcribe_only":
        return "Transkribera ljud" if locale == "sv" else "Transcribe audio"
    if input_type == "json" and output_type == "json":
        return "JSON till JSON" if locale == "sv" else "JSON to JSON"
    if output_type == "json":
        return "Strukturera underlag" if locale == "sv" else "Structure source material"
    if output_type == "docx":
        return "Skapa DOCX" if locale == "sv" else "Create DOCX"
    if output_type == "pdf":
        return "Skapa PDF" if locale == "sv" else "Create PDF"
    if input_type == output_type:
        return _step_type_label(output_type, locale)
    if locale == "sv":
        return f"{_step_type_label(input_type, locale)} till {_step_type_label(output_type, locale)}"
    return f"{_step_type_label(input_type, locale)} to {_step_type_label(output_type, locale)}"


def _step_type_label(value: str, locale: Locale) -> str:
    labels_sv = {
        "audio": "ljud",
        "document": "dokument",
        "file": "fil",
        "json": "JSON",
        "text": "text",
        "docx": "DOCX",
        "pdf": "PDF",
    }
    labels_en = {
        "audio": "audio",
        "document": "document",
        "file": "file",
        "json": "JSON",
        "text": "text",
        "docx": "DOCX",
        "pdf": "PDF",
    }
    labels = labels_sv if locale == "sv" else labels_en
    return labels.get(value, _slot_value(value))


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
        "post_processing_goal": "Syfte med bearbetningen",
        "structured_analysis_need": "Strukturerad analys",
    }
    labels_en = {
        "primary_runtime_input": "Runtime input",
        "terminal_output": "Final output",
        "document_material_scope": "Document source material",
        "runtime_metadata_fields": "Runtime metadata",
        "docx_output_mode": "DOCX output",
        "pdf_generation_mode": "PDF output",
        "post_processing_goal": "Processing purpose",
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


__all__ = [
    "AskCanonicalQuestion",
    "BuilderTurnControl",
    "BuilderTurnDecision",
    "CommitArchitecture",
    "ConfirmRequirements",
    "GenerateProposal",
    "resolve_turn_control",
]
