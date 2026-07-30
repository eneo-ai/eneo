"""Deterministic server-owned Builder turn control.

The model may still generate rich semantic proposal content, but discovery,
architecture commitment, requirements confirmation, and proposal phase
selection are server decisions derived from typed `PlanningState`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeAlias, assert_never

from eneo.flows.ai_builder.ai_builder_action_policy import (
    PlannerActionPolicy,
    build_planner_action_policy,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AIBuilderAttachmentContext,
    render_ai_builder_evidence_value,
)
from eneo.flows.ai_builder.ai_builder_discovery_models import BackendQuestion
from eneo.flows.ai_builder.ai_builder_event_models import (
    KeyDecisionPayload,
    RequirementsSummaryPayload,
    StructuredQuestionOptionPayload,
    StructuredQuestionPayload,
)
from eneo.flows.ai_builder.ai_builder_output_schema_evidence import (
    project_output_schema_fields,
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
    AttachmentCoverage,
    ExampleOutputSchemaInferenceReason,
    FileRole,
    FileRoleEvidence,
    PlanningState,
    ResolvedSlot,
)
from eneo.flows.ai_builder.question_catalog import Locale, render_question

_MAX_CONFIRMATION_ATTACHMENT_DETAILS = 10
_MAX_CONFIRMATION_EXAMPLE_HEADINGS = 8
_MAX_CONFIRMATION_STYLE_CONSTRAINTS = 6
_ATTACHMENT_ASSUMPTION_PREFIX_EN = "Attachment evidence — "
_ATTACHMENT_ASSUMPTION_PREFIX_SV = "Bilageunderlag – "


@dataclass(frozen=True, slots=True)
class AskCanonicalQuestion:
    slot_name: str
    prompt: str


@dataclass(frozen=True, slots=True)
class AskOutputSchemaConflict:
    question: BackendQuestion


@dataclass(frozen=True, slots=True)
class CommitArchitecture:
    architecture_commit: ArchitectureCommitDraft


@dataclass(frozen=True, slots=True)
class ReviseArchitecture:
    architecture_commit: ArchitectureCommitDraft


@dataclass(frozen=True, slots=True)
class ConfirmRequirements:
    payload: RequirementsSummaryPayload
    attachment_evidence_fingerprint: str


@dataclass(frozen=True, slots=True)
class GenerateProposal:
    pass


BuilderTurnDecision: TypeAlias = (
    AskCanonicalQuestion
    | AskOutputSchemaConflict
    | CommitArchitecture
    | ReviseArchitecture
    | ConfirmRequirements
    | GenerateProposal
)


@dataclass(frozen=True, slots=True)
class BuilderTurnControl:
    decision: BuilderTurnDecision


def resolve_turn_control(
    *,
    session_state: PlanningState,
    selected_discovery_question_ids: tuple[str, ...],
    confirmed_attachment_evidence_fingerprint: str | None,
    ui_language: str | None,
    discovery_assumptions: tuple[str, ...] = (),
    attachment_context: AIBuilderAttachmentContext | None = None,
    output_schema_conflict_pending: bool = False,
) -> BuilderTurnControl:
    if output_schema_conflict_pending:
        if attachment_context is None:
            raise ValueError("output schema conflict requires attachment context")
        return BuilderTurnControl(
            decision=AskOutputSchemaConflict(
                question=_output_schema_conflict_question(
                    attachment_context,
                    _locale(ui_language),
                )
            )
        )
    requirements_payload = _confirm_requirements_payload(
        session_state,
        _locale(ui_language),
        discovery_assumptions,
    )
    attachment_evidence_fingerprint = _attachment_evidence_fingerprint(session_state)
    action_policy = build_planner_action_policy(
        session_state=session_state,
        selected_discovery_question_ids=selected_discovery_question_ids,
        requirements_confirmed=(
            confirmed_attachment_evidence_fingerprint == attachment_evidence_fingerprint
        ),
    )
    return BuilderTurnControl(
        decision=_decision_from_policy(
            action_policy=action_policy,
            session_state=session_state,
            requirements_payload=requirements_payload,
            attachment_evidence_fingerprint=attachment_evidence_fingerprint,
            ui_language=ui_language,
        ),
    )


def _attachment_evidence_fingerprint(
    session_state: PlanningState,
) -> str:
    output_schema = session_state.output_schema_evidence
    serialized = json.dumps(
        {
            "file_roles": [
                item.model_dump(mode="json")
                for item in sorted(
                    session_state.file_roles,
                    key=lambda item: str(item.file_id),
                )
            ],
            "output_schema": (
                {
                    "fingerprint": output_schema.fingerprint,
                    "source": output_schema.source,
                    "strength": output_schema.strength,
                    "source_file_ids": [
                        str(file_id) for file_id in output_schema.source_file_ids
                    ],
                }
                if output_schema is not None
                else None
            ),
            "example_output_constraints": (
                session_state.example_output_constraints.model_dump(mode="json")
                if session_state.example_output_constraints is not None
                else None
            ),
            "example_output_schema_inference": (
                session_state.example_output_schema_inference.model_dump(mode="json")
                if session_state.example_output_schema_inference is not None
                else None
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _decision_from_policy(
    *,
    action_policy: PlannerActionPolicy,
    session_state: PlanningState,
    requirements_payload: RequirementsSummaryPayload,
    attachment_evidence_fingerprint: str,
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

    if "revise_architecture" in action_policy.allowed_action_kinds:
        draft = derive_architecture_commit_draft(session_state)
        if draft is not None:
            return ReviseArchitecture(architecture_commit=draft)

    if "confirm_requirements" in action_policy.allowed_action_kinds:
        return ConfirmRequirements(
            payload=requirements_payload,
            attachment_evidence_fingerprint=attachment_evidence_fingerprint,
        )

    if action_policy.allowed_action_kinds == ("propose_plan",):
        return GenerateProposal()

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


def _output_schema_conflict_question(
    attachment_context: AIBuilderAttachmentContext,
    locale: Locale,
) -> BackendQuestion:
    filenames_by_id = {
        item.file_id: render_ai_builder_evidence_value(item.filename)
        for item in attachment_context.evidence
    }
    options: list[StructuredQuestionOptionPayload] = []
    for index, candidate in enumerate(
        attachment_context.output_schema_discovery.candidates,
        start=1,
    ):
        filenames = [
            filenames_by_id[file_id]
            for file_id in candidate.source_file_ids
            if file_id in filenames_by_id
        ]
        visible_filenames = ", ".join(filenames[:2])
        if len(filenames) > 2:
            visible_filenames = f"{visible_filenames} (+{len(filenames) - 2})"
        projection = project_output_schema_fields(candidate.json_schema)
        visible_fields = ", ".join(projection.fields)
        if projection.truncated:
            visible_fields = (
                f"{visible_fields} (+{projection.total_count - len(projection.fields)})"
            )
        if locale == "sv":
            label = (
                f"Schema {index}: {visible_filenames or 'namnlös JSON-fil'} "
                f"({candidate.fingerprint[:8]})"
            )
            description = f"Fält: {visible_fields or 'inga namngivna toppnivåfält'}."
        else:
            label = (
                f"Schema {index}: {visible_filenames or 'unnamed JSON file'} "
                f"({candidate.fingerprint[:8]})"
            )
            description = f"Fields: {visible_fields or 'no named top-level fields'}."
        options.append(
            StructuredQuestionOptionPayload(
                id=candidate.fingerprint,
                label=label,
                value=candidate.fingerprint,
                description=description,
            )
        )
    if locale == "sv":
        question_text = "Vilket av de bifogade JSON-schemana ska styra utdatan?"
        assistant_text = (
            "Jag hittade flera olika uttryckliga JSON-scheman. Välj vilket som "
            "ska styra flödets utdata."
        )
    else:
        question_text = "Which attached JSON schema should control the output?"
        assistant_text = (
            "I found several distinct explicit JSON schemas. Choose which one "
            "should control the flow output."
        )
    return BackendQuestion(
        question_data=StructuredQuestionPayload(
            question_id="output_schema_conflict",
            question=question_text,
            options=options,
            selection_mode="single",
            allow_custom=False,
        ),
        assistant_text=assistant_text,
    )


def _locale(ui_language: str | None) -> Locale:
    return "sv" if ui_language == "sv" else "en"


def _confirm_requirements_payload(
    session_state: PlanningState,
    locale: Locale,
    discovery_assumptions: tuple[str, ...] = (),
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
        if _slot_is_key_decision(resolved[slot_name])
    ]
    architecture_decision = _architecture_decision(session_state, locale)
    if architecture_decision is not None:
        key_decisions.append(architecture_decision)
    input_description = _input_description(resolved, locale)
    output_description = _output_description(resolved, locale)
    summary = _summary_text(resolved, locale)
    output_schema_summary = _output_schema_summary_line(session_state, locale)
    if output_schema_summary is not None:
        summary = f"{summary} {output_schema_summary}"
    return RequirementsSummaryPayload(
        summary=summary,
        key_decisions=key_decisions,
        input_description=input_description,
        output_description=output_description,
        assumptions=[
            *[
                _slot_assumption(slot_name, resolved[slot_name], locale)
                for slot_name in sorted(resolved)
                if not _slot_is_key_decision(resolved[slot_name])
            ],
            *discovery_assumptions,
            *_attachment_assumptions(session_state, locale),
            *_example_output_assumptions(session_state, locale),
            *_assumptions(locale),
        ],
        manual_setup_notes=[],
    )


def _attachment_assumptions(
    session_state: PlanningState,
    locale: Locale,
) -> list[str]:
    ordered = sorted(session_state.file_roles, key=lambda item: str(item.file_id))
    rendered = [
        _attachment_assumption(item, locale)
        for item in ordered[:_MAX_CONFIRMATION_ATTACHMENT_DETAILS]
    ]
    omitted = len(ordered) - len(rendered)
    if omitted <= 0:
        return rendered
    if locale == "sv":
        rendered.append(
            f"{_ATTACHMENT_ASSUMPTION_PREFIX_SV}Ytterligare {omitted} bilagor "
            f"utelämnas från denna sammanfattning ({len(ordered)} totalt)."
        )
    else:
        rendered.append(
            f"{_ATTACHMENT_ASSUMPTION_PREFIX_EN}{omitted} additional attachments "
            f"are omitted from this summary ({len(ordered)} total)."
        )
    return rendered


def _attachment_assumption(
    item: FileRoleEvidence,
    locale: Locale,
) -> str:
    role = _attachment_role_label(item.role, locale)
    coverage = _attachment_coverage_description(
        item.coverage,
        has_readable_text=item.has_readable_text,
        locale=locale,
    )
    filename = render_ai_builder_evidence_value(item.filename)
    if locale == "sv":
        readable = "ja" if item.has_readable_text else "nej"
        return (
            f'{_ATTACHMENT_ASSUMPTION_PREFIX_SV}Bilaga "{filename}": '
            f"vald roll {role}; läsbar text: {readable}; "
            f"täckning: {coverage}."
        )
    readable = "yes" if item.has_readable_text else "no"
    return (
        f'{_ATTACHMENT_ASSUMPTION_PREFIX_EN}Attachment "{filename}": '
        f"selected role {role}; "
        f"readable text: {readable}; coverage: {coverage}."
    )


def _attachment_role_label(role: FileRole, locale: Locale) -> str:
    labels_sv: dict[FileRole, str] = {
        "runtime_input_sample": "Exempel på körningsindata",
        "template": "Mall",
        "reference_material": "Referensmaterial",
        "example_output": "Exempelresultat",
        "context_only": "Endast kontext",
    }
    labels_en: dict[FileRole, str] = {
        "runtime_input_sample": "Runtime input sample",
        "template": "Template",
        "reference_material": "Reference material",
        "example_output": "Example output",
        "context_only": "Context only",
    }
    return (labels_sv if locale == "sv" else labels_en)[role]


def _attachment_coverage_description(
    coverage: AttachmentCoverage,
    *,
    has_readable_text: bool,
    locale: Locale,
) -> str:
    match coverage:
        case "fully_seen":
            return (
                "hela den läsbara texten ingår"
                if locale == "sv"
                else "all readable text is included"
            )
        case "excerpt_truncated":
            return (
                "ett förkortat utdrag av den läsbara texten ingår"
                if locale == "sv"
                else "a truncated excerpt of the readable text is included"
            )
        case "inventory_only":
            if has_readable_text:
                return (
                    "läsbar text finns men inget utdrag ingår"
                    if locale == "sv"
                    else "readable text exists but no excerpt is included"
                )
            return (
                "ingen läsbar text är tillgänglig"
                if locale == "sv"
                else "no readable text is available"
            )
    return assert_never(coverage)


def _output_schema_summary_line(
    session_state: PlanningState,
    locale: Locale,
) -> str | None:
    evidence = session_state.output_schema_evidence
    if evidence is None:
        return None
    projection = project_output_schema_fields(evidence.json_schema)
    field_text = _bounded_projection_text(projection.fields, locale=locale)
    if evidence.source == "template_placeholders":
        if not evidence.truncated or evidence.total_count is None:
            return None
        visible_count = len(projection.fields)
        if locale == "sv":
            return (
                f"Mallen innehåller {evidence.total_count} unika platshållare; "
                f"{visible_count} visas i planeringsunderlaget."
            )
        return (
            f"The template contains {evidence.total_count} unique placeholders; "
            f"{visible_count} are shown in the planning evidence."
        )
    if evidence.strength == "explicit":
        if locale == "sv":
            return (
                "Ett uttryckligt utdataschema styr JSON-resultatet. "
                f"Valda fält: {field_text}."
            )
        return (
            "An explicit output schema controls the JSON result. "
            f"Selected fields: {field_text}."
        )
    if locale == "sv":
        return (
            "En försiktig utdatastruktur har härletts från valt exempelresultat; "
            "den är vägledning och inte ett uttryckligt slutet kontrakt. "
            f"Härledda fält: {field_text}."
        )
    return (
        "A conservative output shape was inferred from the selected example; "
        "it is guidance, not an explicit closed contract. "
        f"Inferred fields: {field_text}."
    )


def _bounded_projection_text(
    fields: tuple[str, ...],
    *,
    locale: Locale,
) -> str:
    if fields:
        return ", ".join(render_ai_builder_evidence_value(field) for field in fields)
    return (
        "inga namngivna toppnivåfält" if locale == "sv" else "no named top-level fields"
    )


def _example_output_assumptions(
    session_state: PlanningState,
    locale: Locale,
) -> list[str]:
    constraints = session_state.example_output_constraints
    if constraints is None:
        return []
    headings = constraints.headings[:_MAX_CONFIRMATION_EXAMPLE_HEADINGS]
    styles = constraints.style_constraints[:_MAX_CONFIRMATION_STYLE_CONSTRAINTS]
    assumptions: list[str] = []
    if headings:
        rendered = ", ".join(
            render_ai_builder_evidence_value(heading) for heading in headings
        )
        omitted = len(constraints.headings) - len(headings)
        if omitted:
            rendered = f"{rendered} (+{omitted})"
        assumptions.append(
            f"Exempelresultatets valda rubriker: {rendered}."
            if locale == "sv"
            else f"Selected example-output headings: {rendered}."
        )
    if styles:
        rendered = "; ".join(
            f"{item.category}: {render_ai_builder_evidence_value(item.description)}"
            for item in styles
        )
        omitted = len(constraints.style_constraints) - len(styles)
        if omitted:
            rendered = f"{rendered}; +{omitted}"
        assumptions.append(
            f"Exempelresultatets stilunderlag: {rendered}."
            if locale == "sv"
            else f"Example-output style evidence: {rendered}."
        )
    assumptions.append(
        (
            "Det valda exemplet vägleder struktur och stil men lovar inte exakt "
            "visuell layout."
        )
        if locale == "sv"
        else (
            "The selected example guides structure and style but does not promise "
            "exact visual layout."
        )
    )
    inference = session_state.example_output_schema_inference
    if inference is not None and inference.status == "not_inferred":
        assumptions.append(_no_inference_assumption(inference.reason, locale))
    return assumptions


def _no_inference_assumption(
    reason: ExampleOutputSchemaInferenceReason | None,
    locale: Locale,
) -> str:
    reasons_sv: dict[ExampleOutputSchemaInferenceReason, str] = {
        "higher_priority_schema": "ett schema med högre prioritet redan styr utdatan",
        "no_json_object": "inget valt exempel var ett JSON-objekt",
        "incomplete_content": "hela JSON-objektet inte var tillgängligt",
        "invalid_json": "JSON-innehållet inte var giltigt",
        "top_level_not_object": "JSON-innehållet inte var ett objekt på toppnivå",
        "raw_bytes": "JSON-exemplet överskred säkerhetsgränsen för storlek",
        "field_count": "JSON-exemplet överskred säkerhetsgränsen för antal fält",
        "depth": "JSON-exemplet överskred säkerhetsgränsen för nästling",
        "conflicting_shapes": "de valda JSON-exemplen hade olika strukturer",
    }
    reasons_en: dict[ExampleOutputSchemaInferenceReason, str] = {
        "higher_priority_schema": "a higher-priority schema already controls the output",
        "no_json_object": "no selected example was a JSON object",
        "incomplete_content": "the complete JSON object was not available",
        "invalid_json": "the JSON content was invalid",
        "top_level_not_object": "the JSON content was not a top-level object",
        "raw_bytes": "the JSON example exceeded the byte safety limit",
        "field_count": "the JSON example exceeded the field-count safety limit",
        "depth": "the JSON example exceeded the nesting safety limit",
        "conflicting_shapes": "the selected JSON examples had different shapes",
    }
    if locale == "sv":
        rendered_reason = (
            reasons_sv[reason]
            if reason is not None
            else "underlaget inte var säkert att tolka"
        )
        return (
            "Ingen JSON-struktur härleddes från exempelresultatet eftersom "
            f"{rendered_reason}."
        )
    rendered_reason = (
        reasons_en[reason]
        if reason is not None
        else "the evidence was not safe to interpret"
    )
    return (
        f"No JSON shape was inferred from the example output because {rendered_reason}."
    )


def _slot_is_key_decision(slot: ResolvedSlot) -> bool:
    match slot.source:
        case "structured_answer" | "requirements_summary" | "flow_default":
            return True
        case "policy_default" | "heuristic" | "model":
            return False
    return assert_never(slot.source)


def _slot_assumption(
    slot_name: str,
    slot: ResolvedSlot,
    locale: Locale,
) -> str:
    return (
        f"{_slot_label(slot_name, locale)}: "
        f"{_slot_value_for_slot(slot_name, slot.value, locale)}"
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
            return summary
        summary = (
            f"The flow should accept {runtime_input or 'runtime input'} "
            f"and deliver {terminal_output or 'a final result'}."
        )
        if post_processing_goal:
            summary += f" The result should help with: {post_processing_goal}."
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
        "report_disposition": "Rapportupplägg",
        "runtime_metadata_fields": "Metadata vid körning",
        "docx_output_mode": "DOCX-resultat",
        "pdf_generation_mode": "PDF-resultat",
        "post_processing_goal": "Syfte med bearbetningen",
    }
    labels_en = {
        "primary_runtime_input": "Runtime input",
        "terminal_output": "Final output",
        "document_material_scope": "Document source material",
        "report_disposition": "Report structure",
        "runtime_metadata_fields": "Runtime metadata",
        "docx_output_mode": "DOCX output",
        "pdf_generation_mode": "PDF output",
        "post_processing_goal": "Processing purpose",
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
    "ReviseArchitecture",
    "resolve_turn_control",
]
