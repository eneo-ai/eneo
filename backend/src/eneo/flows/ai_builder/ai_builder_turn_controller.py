"""Deterministic server-owned Builder turn control.

The model may still generate rich semantic proposal content, but discovery,
architecture commitment, requirements confirmation, and proposal phase
selection are server decisions derived from typed `PlanningState`.

The requirements disclosure is built before this module runs
(`ai_builder_requirements_disclosure`), so turn control only compares the
version the user confirmed against the version of the disclosure it was
handed. There is no second confirmation identity.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeAlias

from eneo.flows.ai_builder.ai_builder_action_policy import (
    NAMED_RESULT_PROJECTION_MAX_ITEMS,
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
from eneo.flows.ai_builder.ai_builder_error_contract import AIBuilderErrorCode
from eneo.flows.ai_builder.ai_builder_event_models import (
    RequirementsSummaryPayload,
    StructuredQuestionOptionPayload,
    StructuredQuestionPayload,
)
from eneo.flows.ai_builder.ai_builder_requirements_disclosure import resolve_locale
from eneo.flows.ai_builder.ai_builder_schema_evidence import (
    DeclaredSchemaCandidate,
    project_schema_fields,
)
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommitDraft,
    PlanningState,
)
from eneo.flows.ai_builder.question_catalog import (
    RUNTIME_METADATA_FIELD_PURPOSES,
    Locale,
    runtime_metadata_field_details_question,
    runtime_metadata_field_details_rationale,
    runtime_metadata_field_purpose_label,
)

_UNSUPPORTED_ARCHITECTURE_MESSAGE_EN = (
    "This combination of input and final output is not supported. Start fresh "
    "and choose a different input or final output."
)
_UNSUPPORTED_ARCHITECTURE_MESSAGE_SV = (
    "Den här kombinationen av indata och slutresultat stöds inte. Börja om "
    "och välj en annan indata eller ett annat slutresultat."
)
_ARCHITECTURE_REFUSAL_MESSAGES: Mapping[AIBuilderErrorCode, Mapping[Locale, str]] = {
    AIBuilderErrorCode.UNSUPPORTED_ARCHITECTURE: {
        "en": _UNSUPPORTED_ARCHITECTURE_MESSAGE_EN,
        "sv": _UNSUPPORTED_ARCHITECTURE_MESSAGE_SV,
    },
    AIBuilderErrorCode.PDF_TEMPLATE_UNSUPPORTED: {
        "en": (
            "Filling a fixed PDF template is not supported. Choose a normal "
            "generated PDF. If a fixed template is mandatory, use a DOCX "
            "template-based Flow instead."
        ),
        "sv": (
            "Det går inte att fylla i en fast PDF-mall. Välj en vanlig genererad "
            "PDF. Om en fast mall är ett krav behöver du i stället använda ett "
            "flöde som bygger på en DOCX-mall."
        ),
    },
    AIBuilderErrorCode.TRANSCRIPT_CHECKPOINT_REQUIRES_AUDIO: {
        "en": (
            "A transcript review checkpoint requires audio as the runtime input. "
            "Choose audio input or remove the transcript checkpoint and try again."
        ),
        "sv": (
            "En granskningspunkt för transkribering kräver ljud som indata vid "
            "körning. Välj ljud som indata eller ta bort granskningen av "
            "transkriberingen och försök igen."
        ),
    },
    AIBuilderErrorCode.TEMPLATE_ATTACHMENT_SELECTION_INVALID: {
        "en": (
            "A template-fill Flow requires exactly one selected DOCX template. "
            "Attach or select one DOCX template and try again."
        ),
        "sv": (
            "Ett flöde som fyller i en mall kräver exakt en vald DOCX-mall. "
            "Bifoga eller välj en DOCX-mall och försök igen."
        ),
    },
    AIBuilderErrorCode.TEMPLATE_ATTACHMENT_UNREADABLE: {
        "en": (
            "The selected DOCX template could not be inspected safely. Attach a "
            "valid DOCX file and try again."
        ),
        "sv": (
            "Den valda DOCX-mallen kunde inte läsas på ett säkert sätt. Bifoga en "
            "giltig DOCX-fil och försök igen."
        ),
    },
    AIBuilderErrorCode.SCHEMA_LIMIT_EXCEEDED: {
        "en": (
            "Without an attached output schema, at most "
            f"{NAMED_RESULT_PROJECTION_MAX_ITEMS} named result fields can be "
            "built for you, and this flow names more. Name fewer result fields, "
            "or attach the output schema you want, and try again."
        ),
        "sv": (
            "Utan ett bifogat utdataschema kan högst "
            f"{NAMED_RESULT_PROJECTION_MAX_ITEMS} namngivna resultatfält byggas "
            "åt dig, och flödet namnger fler. Namnge färre resultatfält, eller "
            "bifoga det utdataschema du vill ha, och försök igen."
        ),
    },
    AIBuilderErrorCode.NAMED_RESULT_KEY_UNSUPPORTED: {
        "en": (
            "One of the named result fields cannot be used as a key in a "
            "structured result. Use names of letters, digits and underscores "
            "that begin with a letter, and try again."
        ),
        "sv": (
            "Ett av de namngivna resultatfälten kan inte användas som nyckel i "
            "ett strukturerat resultat. Använd namn med bokstäver, siffror och "
            "understreck som börjar med en bokstav, och försök igen."
        ),
    },
}


@dataclass(frozen=True, slots=True)
class AskCanonicalQuestion:
    slot_name: str
    question: BackendQuestion | None = None
    # The questions still queued behind this one, counted from the ordered
    # ask queue this decision was taken from. None for the questions decided
    # ahead of that queue, where no ranked plan stands behind the ask.
    planned_remaining: int | None = None


@dataclass(frozen=True, slots=True)
class CommitArchitecture:
    architecture_commit: ArchitectureCommitDraft


@dataclass(frozen=True, slots=True)
class ReviseArchitecture:
    architecture_commit: ArchitectureCommitDraft


@dataclass(frozen=True, slots=True)
class ConfirmRequirements:
    payload: RequirementsSummaryPayload


@dataclass(frozen=True, slots=True)
class GenerateProposal:
    pass


@dataclass(frozen=True, slots=True)
class RefuseArchitectureCommit:
    code: AIBuilderErrorCode
    message: str


BuilderTurnDecision: TypeAlias = (
    AskCanonicalQuestion
    | CommitArchitecture
    | ReviseArchitecture
    | ConfirmRequirements
    | GenerateProposal
    | RefuseArchitectureCommit
)


@dataclass(frozen=True, slots=True)
class BuilderTurnControl:
    decision: BuilderTurnDecision


def resolve_turn_control(
    *,
    session_state: PlanningState,
    selected_discovery_question_ids: tuple[str, ...],
    requirements_disclosure: RequirementsSummaryPayload,
    confirmed_requirements_version: str | None,
    ui_language: str | None,
    attachment_context: AIBuilderAttachmentContext | None = None,
    schema_candidates: tuple[DeclaredSchemaCandidate, ...] = (),
    schema_direction_pending: bool = False,
    requirements_confirmation_required: bool = True,
    is_edit_mode: bool = False,
) -> BuilderTurnControl:
    locale = resolve_locale(ui_language)
    action_policy = build_planner_action_policy(
        session_state=session_state,
        selected_discovery_question_ids=selected_discovery_question_ids,
        is_edit_mode=is_edit_mode,
        schema_direction_pending=schema_direction_pending,
        requirements_confirmed=(
            not requirements_confirmation_required
            or (
                confirmed_requirements_version is not None
                and confirmed_requirements_version
                == requirements_disclosure.requirements_version
            )
        ),
    )
    if action_policy.allowed_action_kinds == ("refuse_architecture_commit",):
        refusal_code = action_policy.architecture_refusal_code
        if refusal_code is None:
            raise ValueError("architecture refusal action requires a public error code")
        return BuilderTurnControl(
            decision=RefuseArchitectureCommit(
                code=refusal_code,
                message=_ARCHITECTURE_REFUSAL_MESSAGES[refusal_code][locale],
            )
        )
    if action_policy.allowed_action_kinds == ("revise_architecture",):
        draft = derive_architecture_commit_draft(session_state)
        if draft is None:
            raise ValueError("architecture revision action requires a derived draft")
        return BuilderTurnControl(
            decision=ReviseArchitecture(architecture_commit=draft)
        )
    if schema_direction_pending:
        if not schema_candidates:
            raise ValueError("pending schema direction requires candidates")
        question = _schema_direction_question(
            schema_candidates,
            attachment_context=attachment_context,
            locale=locale,
        )
        return BuilderTurnControl(
            decision=AskCanonicalQuestion(
                slot_name="schema_direction",
                question=question,
            )
        )
    if action_policy.allowed_action_kinds == (
        "confirm_requirements",
    ) and _runtime_input_field_details_required(session_state):
        return BuilderTurnControl(
            decision=AskCanonicalQuestion(
                slot_name="runtime_metadata_field_details",
                question=_runtime_input_field_details_question(locale),
            )
        )
    return BuilderTurnControl(
        decision=_decision_from_policy(
            action_policy=action_policy,
            session_state=session_state,
            requirements_disclosure=requirements_disclosure,
        ),
    )


def _runtime_input_field_details_required(session_state: PlanningState) -> bool:
    return (
        session_state.commit_grade_slot_value("runtime_metadata_fields")
        in {"basic_runtime_metadata", "detailed_runtime_metadata"}
        and not session_state.input_fields
    )


def _runtime_input_field_details_question(locale: Locale) -> BackendQuestion:
    question_text = runtime_metadata_field_details_question(locale)
    return BackendQuestion(
        question_data=StructuredQuestionPayload(
            question_id="runtime_metadata_field_details",
            question=question_text,
            options=[
                StructuredQuestionOptionPayload(
                    id=purpose,
                    label=runtime_metadata_field_purpose_label(purpose, locale),
                    value=purpose,
                )
                for purpose in RUNTIME_METADATA_FIELD_PURPOSES
            ],
            selection_mode="single",
            allow_custom=False,
            requires_confirm=True,
            input_field_collection=True,
        ),
        assistant_text=runtime_metadata_field_details_rationale(locale),
    )


def _decision_from_policy(
    *,
    action_policy: PlannerActionPolicy,
    session_state: PlanningState,
    requirements_disclosure: RequirementsSummaryPayload,
) -> BuilderTurnDecision:
    if "ask_question" in action_policy.allowed_action_kinds:
        targets = action_policy.allowed_ask_question_targets
        target = _first(targets)
        if target is not None:
            # The queue is asked head-first, so everything behind the head is
            # what the interview currently intends to ask next.
            return AskCanonicalQuestion(
                slot_name=target,
                planned_remaining=len(targets) - 1,
            )

    if (
        "commit_architecture" in action_policy.allowed_action_kinds
        and session_state.architecture_commit is None
    ):
        draft = derive_architecture_commit_draft(session_state)
        if draft is not None:
            return CommitArchitecture(architecture_commit=draft)

    if "confirm_requirements" in action_policy.allowed_action_kinds:
        return ConfirmRequirements(payload=requirements_disclosure)

    if action_policy.allowed_action_kinds == ("propose_plan",):
        return GenerateProposal()

    raise ValueError(
        "No Builder turn decision can be derived from action policy "
        f"{action_policy.allowed_action_kinds!r}"
    )


def _schema_direction_question(
    candidates: tuple[DeclaredSchemaCandidate, ...],
    *,
    attachment_context: AIBuilderAttachmentContext | None,
    locale: Locale,
) -> BackendQuestion:
    filenames_by_id = {
        item.file_id: render_ai_builder_evidence_value(item.filename)
        for item in (
            attachment_context.evidence if attachment_context is not None else ()
        )
    }
    options: list[StructuredQuestionOptionPayload] = []
    candidate_summaries: list[tuple[DeclaredSchemaCandidate, str, str]] = []
    for index, candidate in enumerate(
        sorted(candidates, key=lambda item: item.fingerprint),
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
        projection = project_schema_fields(candidate.json_schema)
        visible_fields = ", ".join(projection.fields)
        if projection.truncated:
            visible_fields = (
                f"{visible_fields} (+{projection.total_count - len(projection.fields)})"
            )
        source = visible_filenames or (
            "konversationen" if locale == "sv" else "conversation"
        )
        schema_label = f"Schema {index} ({candidate.fingerprint[:8]})"
        description = (
            f"Källa: {source}. Fält: {visible_fields or 'inga namngivna toppnivåfält'}."
            if locale == "sv"
            else f"Source: {source}. Fields: {visible_fields or 'no named top-level fields'}."
        )
        candidate_summaries.append((candidate, schema_label, description))
    for candidate, schema_label, description in candidate_summaries:
        for boundary in ("input", "output"):
            direction_label = (
                "Indata"
                if boundary == "input" and locale == "sv"
                else "Utdata"
                if boundary == "output" and locale == "sv"
                else "Input"
                if boundary == "input"
                else "Output"
            )
            value = f"{boundary}:{candidate.fingerprint}"
            options.append(
                StructuredQuestionOptionPayload(
                    id=value,
                    label=f"{direction_label} — {schema_label}",
                    value=value,
                    description=description,
                )
            )
    options.append(
        StructuredQuestionOptionPayload(
            id="reference_only",
            label=("Endast referens" if locale == "sv" else "Reference only"),
            value="reference_only",
            description=(
                "Använd schemana som underlag utan att låta dem styra indata eller utdata."
                if locale == "sv"
                else "Use the schemas as reference material without assigning an input or output boundary."
            ),
        )
    )
    if locale == "sv":
        question_text = "Hur ska de upptäckta JSON-schemana användas i flödet?"
        assistant_text = (
            "Jag hittade JSON-scheman men behöver veta om de beskriver flödets "
            "indata, utdata, båda eller endast referensmaterial."
        )
    else:
        question_text = "How should the discovered JSON schemas be used in the flow?"
        assistant_text = (
            "I found JSON schemas and need to know whether they describe the flow "
            "input, output, both, or reference material only."
        )
    return BackendQuestion(
        question_data=StructuredQuestionPayload(
            question_id="schema_direction",
            question=question_text,
            options=options,
            selection_mode="multi",
            allow_custom=False,
            requires_confirm=True,
        ),
        assistant_text=assistant_text,
    )


def _first(values: tuple[str, ...]) -> str | None:
    return values[0] if values else None


__all__ = [
    "AskCanonicalQuestion",
    "BuilderTurnControl",
    "BuilderTurnDecision",
    "CommitArchitecture",
    "ConfirmRequirements",
    "GenerateProposal",
    "RefuseArchitectureCommit",
    "ReviseArchitecture",
    "resolve_turn_control",
]
