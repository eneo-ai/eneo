"""The one confirmation disclosure: all user-confirmable planning evidence.

A Builder confirmation has a single truth. This module renders the complete
`RequirementsSummaryPayload` from typed planning state and stamps it with the
requirements version that hashes it. Turn control compares that version,
dispatch persists and emits the same object, and nothing rewrites it
afterwards.

The rendering is a pure function of planning state, locale and the
deterministic discovery assumptions. The stable planning evidence a user can
attest to is disclosed here, so evidence the user cannot see can never inherit
a confirmation the user already gave. Runtime inputs that are revalidated on
every proposal — the current resource catalog, raw attachment excerpts, token
budgets — are not requirements truth and are deliberately outside it.

The disclosure is rendered twice: once clipped for reading, once whole for
identity. Two evidence values that differ only past the display clip are two
different disclosures.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import assert_never

from eneo.flows.ai_builder.ai_builder_action_policy import (
    named_result_projection,
)
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    render_ai_builder_evidence_value,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    AssumptionRowPayload,
    AttachmentRowPayload,
    KeyDecisionPayload,
    NamedContentFieldPayload,
    RequirementsDisclosureContent,
    RequirementsSummaryPayload,
    ResolvedRequirementPayload,
    RunPreviewPayload,
    RunPreviewTemplatePayload,
    RuntimeInputFieldPayload,
)
from eneo.flows.ai_builder.ai_builder_form_intake_signals import (
    FORM_INTAKE_SIGNAL_ID,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import (
    DEFAULT_FINAL_OUTPUT_NEEDS_REVIEW_EN,
    DEFAULT_FINAL_OUTPUT_NEEDS_REVIEW_SV,
    DEFAULT_REQUIREMENTS_SUMMARY_EN,
    DEFAULT_REQUIREMENTS_SUMMARY_SV,
    DEFAULT_RUNTIME_INPUT_NEEDS_REVIEW_EN,
    DEFAULT_RUNTIME_INPUT_NEEDS_REVIEW_SV,
    build_requirements_version,
)
from eneo.flows.ai_builder.ai_builder_result_contract import (
    RESULT_OBLIGATION_SIGNAL_ID,
    RESULT_OBLIGATION_VALUES,
    ResultObligation,
    derive_result_contract,
)
from eneo.flows.ai_builder.ai_builder_schema_evidence import project_schema_fields
from eneo.flows.ai_builder.planning_state import (
    AttachmentCoverage,
    CheckpointIntent,
    CheckpointProducerKind,
    ConfirmedRuntimeMetadataField,
    ExactNamedResultPlacement,
    ExampleOutputSchemaInferenceReason,
    FileRole,
    FileRoleEvidence,
    NamedResultEvidence,
    PlanningState,
    ResolvedSlot,
    SchemaEvidence,
    UnplacedNamedResultPlacement,
    named_result_location_id,
)
from eneo.flows.ai_builder.question_catalog import (
    QUESTION_CATALOG,
    Locale,
    legal_slot_values,
    render_question,
    render_summary_label,
    runtime_metadata_field_purpose_label,
)
from eneo.flows.enums import FlowAuthoringOutputMode
from eneo.flows.flow_review_policy import FlowStepReviewMode

_ATTACHMENT_ASSUMPTION_PREFIX_EN = "Attachment evidence — "
_ATTACHMENT_ASSUMPTION_PREFIX_SV = "Bilageunderlag – "

# How an evidence value reaches the reader. Display clips long values so the
# summary stays readable; identity keeps them whole so two values that clip
# alike still hash apart.
RenderEvidenceValue = Callable[[str], str]


def resolve_locale(ui_language: str | None) -> Locale:
    return "sv" if ui_language == "sv" else "en"


def _whole_evidence_value(value: str) -> str:
    """The whole value, with its own boundary preserved.

    Identity composes values into one line with a separator the values may
    themselves contain. Quoted, `["A, B", "C"]` and `["A", "B, C"]` stay two
    disclosures instead of collapsing into one.
    """

    return json.dumps(" ".join(value.split()), ensure_ascii=False)


def build_requirements_disclosure(
    session_state: PlanningState,
    *,
    ui_language: str | None,
    is_edit_mode: bool = False,
) -> RequirementsSummaryPayload:
    """Render the complete disclosure and stamp the version that hashes it."""

    locale = resolve_locale(ui_language)
    identity = _disclosure_content(
        session_state,
        locale,
        render_value=_whole_evidence_value,
        is_edit_mode=is_edit_mode,
        include_named_content_details=True,
    )
    display = _disclosure_content(
        session_state,
        locale,
        render_value=render_ai_builder_evidence_value,
        is_edit_mode=is_edit_mode,
        include_named_content_details=False,
    )
    return RequirementsSummaryPayload(
        **display.model_dump(),
        requirements_version=build_requirements_version(identity),
        named_content_fields=_named_content_fields(
            session_state,
            locale,
            render_value=render_ai_builder_evidence_value,
        ),
        runtime_input_fields=_runtime_input_fields(session_state, locale),
        weak_role_file_ids=[
            item.file_id
            for item in sorted(
                session_state.file_roles, key=lambda item: str(item.file_id)
            )
            if item.confidence != "high"
        ],
    )


def _runtime_input_fields(
    session_state: PlanningState,
    locale: Locale,
) -> list[RuntimeInputFieldPayload]:
    """The runtime form as items, from the state the sentence is rendered from.

    Order, membership and stated facts follow `_runtime_input_field_assumptions`
    exactly: both read `input_fields`, so the card's field list and the
    sentence above it cannot name different fields or say different things
    about one. That is also why this list needs no place of its own in the
    hash — every fact it shows already reaches the confirmation identity
    through that sentence.

    Values stay whole rather than clipped, because a field's key, label and
    options are the identities the compiled form will carry; the sentence
    clips because it composes every field into one line, and a list gives
    each field its own row.
    """

    return [
        RuntimeInputFieldPayload(
            key=field.value.variable_name,
            label=field.value.label,
            type=field.value.field_type,
            required=field.value.required,
            purpose=runtime_metadata_field_purpose_label(field.purpose, locale),
            options=list(field.value.options),
        )
        for field in session_state.input_fields
    ]


def _named_content_fields(
    session_state: PlanningState,
    locale: Locale,
    *,
    render_value: RenderEvidenceValue,
) -> list[NamedContentFieldPayload]:
    """The named result obligations as readable, editable items.

    The display summary omits this potentially long identifier list, while the
    confirmation identity renders every obligation in full. This projection
    therefore remains outside the hash: it is another view of facts already
    present in the identity, plus display-only origin provenance.
    """

    return [
        NamedContentFieldPayload(
            id=named_result_location_id(obligation),
            # The raw leaf spelling: the card's hierarchy and placement
            # affordance key on identities, never on the display label
            # (which carries shape prose).
            name=obligation.name,
            label=_named_result_text(
                obligation,
                locale,
                render_value=render_value,
                include_placement=False,
            ),
            segments=(
                list(obligation.placement.segments)
                if isinstance(obligation.placement, ExactNamedResultPlacement)
                else []
            ),
            unplaced=isinstance(obligation.placement, UnplacedNamedResultPlacement),
            can_contain_fields=obligation.declared_shape is not None,
            origin=obligation.origin,
        )
        for obligation in session_state.named_result_evidence
    ]


def _disclosure_content(
    session_state: PlanningState,
    locale: Locale,
    *,
    render_value: RenderEvidenceValue,
    is_edit_mode: bool,
    include_named_content_details: bool,
) -> RequirementsDisclosureContent:
    resolved = session_state.resolved_slots
    key_decisions = [
        KeyDecisionPayload(
            topic=render_summary_label(slot_name, locale),
            decision=_slot_value_for_slot(
                slot_name,
                resolved[slot_name].value,
                locale,
            ),
            question_id=_settling_question_id(slot_name, resolved[slot_name]),
            is_derived=resolved[slot_name].source != "structured_answer",
        )
        for slot_name in sorted(resolved)
        if _slot_is_key_decision(resolved[slot_name])
    ]
    architecture_decision = _architecture_decision(session_state, locale)
    if architecture_decision is not None:
        key_decisions.append(architecture_decision)
    key_decisions.extend(
        _checkpoint_decision(intent, locale)
        for intent in session_state.checkpoint_intents
    )
    input_description = _input_description(resolved, locale)
    output_description = _output_description(resolved, locale)
    summary = _summary_text(resolved, locale)
    schema_summary_lines = _schema_summary_lines(
        session_state,
        locale,
        render_value=render_value,
        is_edit_mode=is_edit_mode,
        include_named_content_details=include_named_content_details,
    )
    if schema_summary_lines:
        summary = f"{summary} {' '.join(schema_summary_lines)}"
    return RequirementsDisclosureContent(
        summary=summary,
        key_decisions=key_decisions,
        input_description=input_description,
        output_description=output_description,
        assumption_rows=_assumption_rows(session_state, locale),
        attachment_rows=_attachment_rows(session_state),
        run_preview=_run_preview(session_state),
        resolved_requirements=[
            ResolvedRequirementPayload(
                requirement_id=slot_name,
                selected_value=resolved[slot_name].value,
            )
            for slot_name in sorted(resolved)
            if slot_name in QUESTION_CATALOG
            and resolved[slot_name].source != "attachment_structure"
            and resolved[slot_name].value in legal_slot_values(slot_name)
        ],
        assumptions=[
            *[
                _slot_assumption(slot_name, resolved[slot_name], locale)
                for slot_name in sorted(resolved)
                if not _slot_is_key_decision(resolved[slot_name])
                and slot_name not in QUESTION_CATALOG
            ],
            *_runtime_input_field_assumptions(
                session_state, locale, render_value=render_value
            ),
            *_mapped_file_limit_assumptions(session_state, locale),
            *_secondary_obligation_assumptions(
                session_state, locale, render_value=render_value
            ),
            *_attachment_assumptions(session_state, locale, render_value=render_value),
            *_example_output_assumptions(
                session_state, locale, render_value=render_value
            ),
        ],
        manual_setup_notes=[],
    )


def _assumption_rows(
    session_state: PlanningState,
    locale: Locale,
) -> list[AssumptionRowPayload]:
    """Every settled requirement the user did not answer, as a reopenable row.

    The set is the assumption bucket the prose list used to carry for slots:
    whatever `_slot_is_key_decision` does not promote. It includes values the
    user accepted on an earlier card, so accepting a card re-renders the same
    rows; the card itself decides whether a row can still be reopened.
    """

    rows: list[AssumptionRowPayload] = []
    resolved = session_state.resolved_slots
    for slot_name in sorted(resolved):
        slot = resolved[slot_name]
        if _slot_is_key_decision(slot) or slot_name not in QUESTION_CATALOG:
            continue
        rendered = render_question(slot_name, locale)
        label = next(
            (option.label for option in rendered.options if option.value == slot.value),
            _slot_value_for_slot(slot_name, slot.value, locale),
        )
        rows.append(
            AssumptionRowPayload(
                question_id=slot_name,
                slot_name=slot_name,
                value=slot.value,
                topic=render_summary_label(slot_name, locale),
                label=label,
            )
        )
    return rows


def _runtime_input_field_assumptions(
    session_state: PlanningState,
    locale: Locale,
    *,
    render_value: RenderEvidenceValue,
) -> list[str]:
    """The runtime form the flow will ask its operator to fill in."""

    if not session_state.input_fields:
        return []
    rendered = "; ".join(
        _runtime_input_field_text(field, locale, render_value=render_value)
        for field in session_state.input_fields
    )
    return [
        f"Fält som fylls i vid körning: {rendered}."
        if locale == "sv"
        else f"Fields collected at runtime: {rendered}."
    ]


def _runtime_input_field_text(
    field: ConfirmedRuntimeMetadataField,
    locale: Locale,
    *,
    render_value: RenderEvidenceValue,
) -> str:
    """Everything about one field that the user is attesting to.

    The purpose decides which step the value is placed on and the options are
    what the operator may pick, so both change the compiled flow. A field
    stated without them would let a confirmation the user already gave
    authorize a flow they never read. The line is longer for it; the card
    lists the same fields as items for reading.
    """

    label = render_value(field.value.label)
    name = render_value(field.value.variable_name)
    required = (
        ("obligatoriskt" if field.value.required else "valfritt")
        if locale == "sv"
        else ("required" if field.value.required else "optional")
    )
    stated = [
        name,
        field.value.field_type,
        required,
        runtime_metadata_field_purpose_label(field.purpose, locale),
    ]
    if field.value.options:
        # Quoted before rendering, so the reader and the hash agree on where
        # one choice ends: an option may itself contain the separator, and
        # two choices must not read as the three a bare comma-separated list
        # would suggest. Typographic quotes, because the display rendering
        # escapes a straight one into the reader's line.
        open_quote, close_quote = ("”", "”") if locale == "sv" else ("“", "”")
        options = ", ".join(
            render_value(f"{open_quote}{option}{close_quote}")
            for option in field.value.options
        )
        stated.append(f"val: {options}" if locale == "sv" else f"choices: {options}")
    return f"{label} ({', '.join(stated)})"


def _mapped_file_limit_assumptions(
    session_state: PlanningState,
    locale: Locale,
) -> list[str]:
    """The accepted per-run file limit becomes the compiled `runtime_max_files`."""

    accepted = session_state.mapped_file_limit.accepted_value
    if accepted is None:
        return []
    return [
        f"Högst {accepted} filer behandlas i samma körning."
        if locale == "sv"
        else f"At most {accepted} files are processed in one run."
    ]


# The obligation vocabulary is closed, so the card names each one in the
# reader's language instead of echoing the classifier's identifiers.
_RESULT_OBLIGATION_LABELS: dict[ResultObligation, tuple[str, str]] = {
    "summary": ("sammanfattning", "summary"),
    "key_facts": ("viktiga fakta", "key facts"),
    "decisions": ("beslut", "decisions"),
    "actions": ("åtgärder", "actions"),
    "owners": ("ansvariga", "owners"),
    "deadlines": ("tidsfrister", "deadlines"),
    "open_questions": ("öppna frågor", "open questions"),
    "risks": ("risker", "risks"),
    "deviations": ("avvikelser", "deviations"),
    "comparison_basis": ("jämförelseunderlag", "comparison basis"),
    "recommendations": ("rekommendationer", "recommendations"),
    "missing_information_policy": (
        "hantering av uppgifter som saknas",
        "handling of missing information",
    ),
}


def _result_obligation_labels(session_state: PlanningState, locale: Locale) -> str:
    present = {
        signal.value
        for signal in session_state.signals
        if signal.question_id == RESULT_OBLIGATION_SIGNAL_ID
    }
    return ", ".join(
        _RESULT_OBLIGATION_LABELS[value][0 if locale == "sv" else 1]
        for value in RESULT_OBLIGATION_VALUES
        if value in present
    )


def _secondary_obligation_assumptions(
    session_state: PlanningState,
    locale: Locale,
    *,
    render_value: RenderEvidenceValue,
) -> list[str]:
    """Typed planning signals that reach the compiled plan.

    Result obligations become the compiled result contract; form-intake
    signals decide whether the flow collects fields at all. Neither is
    derivable from the resolved slots, so both are disclosed — and separately,
    because they promise different things.
    """

    assumptions: list[str] = []
    obligations = _result_obligation_labels(session_state, locale)
    if obligations:
        assumptions.append(
            f"Resultatet ska också innehålla: {obligations}."
            if locale == "sv"
            else f"The result must also include: {obligations}."
        )
    form_intake = _signal_values(
        session_state, FORM_INTAKE_SIGNAL_ID, render_value=render_value
    )
    if form_intake:
        assumptions.append(
            f"Underlag om formulärfält vid körning: {form_intake}."
            if locale == "sv"
            else f"Runtime form-field evidence: {form_intake}."
        )
    return assumptions


def _signal_values(
    session_state: PlanningState,
    question_id: str,
    *,
    render_value: RenderEvidenceValue,
) -> str:
    return ", ".join(
        render_value(value)
        for value in sorted(
            {
                signal.value
                for signal in session_state.signals
                if signal.question_id == question_id
            }
        )
    )


def _checkpoint_decision(
    intent: CheckpointIntent,
    locale: Locale,
) -> KeyDecisionPayload:
    topics_sv: dict[CheckpointProducerKind, str] = {
        "transcript": "Granskning av transkribering",
        "structured_result": "Granskning av strukturerat resultat",
        "report_text": "Granskning av rapporttext",
    }
    topics_en: dict[CheckpointProducerKind, str] = {
        "transcript": "Transcript review",
        "structured_result": "Structured-result review",
        "report_text": "Report-text review",
    }
    decisions_sv: dict[
        tuple[CheckpointProducerKind, FlowStepReviewMode],
        str,
    ] = {
        ("transcript", FlowStepReviewMode.VIEW): (
            "Transkriberingen måste godkännas innan flödet fortsätter."
        ),
        ("transcript", FlowStepReviewMode.EDIT): (
            "Transkriberingen kan redigeras innan flödet fortsätter."
        ),
        ("structured_result", FlowStepReviewMode.VIEW): (
            "Det strukturerade resultatet måste godkännas innan flödet fortsätter."
        ),
        ("structured_result", FlowStepReviewMode.EDIT): (
            "Det strukturerade resultatet kan redigeras innan flödet fortsätter."
        ),
        ("report_text", FlowStepReviewMode.VIEW): (
            "Rapporttexten måste godkännas innan flödet fortsätter."
        ),
        ("report_text", FlowStepReviewMode.EDIT): (
            "Rapporttexten kan redigeras innan flödet fortsätter."
        ),
    }
    decisions_en: dict[
        tuple[CheckpointProducerKind, FlowStepReviewMode],
        str,
    ] = {
        ("transcript", FlowStepReviewMode.VIEW): (
            "The transcript must be approved before the flow continues."
        ),
        ("transcript", FlowStepReviewMode.EDIT): (
            "The transcript can be edited before the flow continues."
        ),
        ("structured_result", FlowStepReviewMode.VIEW): (
            "The structured result must be approved before the flow continues."
        ),
        ("structured_result", FlowStepReviewMode.EDIT): (
            "The structured result can be edited before the flow continues."
        ),
        ("report_text", FlowStepReviewMode.VIEW): (
            "The report text must be approved before the flow continues."
        ),
        ("report_text", FlowStepReviewMode.EDIT): (
            "The report text can be edited before the flow continues."
        ),
    }
    cleared_sv: dict[CheckpointProducerKind, str] = {
        "transcript": ("Granskningen av transkriberingen är borttagen på din begäran."),
        "structured_result": (
            "Granskningen av det strukturerade resultatet är borttagen på din begäran."
        ),
        "report_text": "Granskningen av rapporttexten är borttagen på din begäran.",
    }
    cleared_en: dict[CheckpointProducerKind, str] = {
        "transcript": "The transcript review is removed at your request.",
        "structured_result": (
            "The structured-result review is removed at your request."
        ),
        "report_text": "The report-text review is removed at your request.",
    }
    if intent.mode is None:
        decision = (cleared_sv if locale == "sv" else cleared_en)[intent.producer_kind]
    else:
        decision = (decisions_sv if locale == "sv" else decisions_en)[
            (intent.producer_kind, intent.mode)
        ]
    return KeyDecisionPayload(
        topic=(topics_sv if locale == "sv" else topics_en)[intent.producer_kind],
        decision=decision,
    )


def _attachment_assumptions(
    session_state: PlanningState,
    locale: Locale,
    *,
    render_value: RenderEvidenceValue,
) -> list[str]:
    # Every attachment, never a truncated head plus a count: an undisclosed
    # role is still plan-driving — the architecture refusal inspects every
    # selected template — so hiding one lets a plan change inherit a
    # confirmation the user gave for something else.
    ordered = sorted(session_state.file_roles, key=lambda item: str(item.file_id))
    travels = _attachment_travels(session_state)
    return [
        _attachment_assumption(
            item,
            locale,
            render_value=render_value,
            travels=travels(item),
        )
        for item in ordered
    ]


def _attachment_travels(
    session_state: PlanningState,
) -> Callable[[FileRoleEvidence], bool]:
    """Whether an attachment travels with the flow: the commit's decision.

    Only a template can travel, and only when the committed architecture fills
    a template and exactly one attached template exists; the plan lifecycle
    promotes it under the same rule. The prose row and the typed row read
    this one predicate.
    """

    commit = session_state.architecture_commit
    template_fill = (
        commit is not None
        and bool(commit.tuples_chain)
        and commit.tuples_chain[-1].output_mode is FlowAuthoringOutputMode.TEMPLATE_FILL
    )
    template_count = sum(item.role == "template" for item in session_state.file_roles)
    return lambda item: (
        template_fill and item.role == "template" and template_count == 1
    )


def _attachment_rows(session_state: PlanningState) -> list[AttachmentRowPayload]:
    travels = _attachment_travels(session_state)
    return [
        AttachmentRowPayload(
            file_id=item.file_id,
            filename=item.filename,
            role=item.role,
            readable=item.has_readable_text,
            coverage=item.coverage,
            travels=travels(item),
            placeholders=item.template_placeholders,
        )
        for item in sorted(session_state.file_roles, key=lambda item: str(item.file_id))
    ]


def _run_preview(session_state: PlanningState) -> RunPreviewPayload | None:
    """The contract a run will follow, from commit-grade slots and the commit."""

    contract = derive_result_contract(session_state)
    runtime_input = session_state.commit_grade_slot_value("primary_runtime_input")
    result_type = session_state.commit_grade_slot_value("terminal_output")
    commit = session_state.architecture_commit
    travels = _attachment_travels(session_state)
    template = next(
        (
            RunPreviewTemplatePayload(
                filename=item.filename,
                placeholder_count=len(item.template_placeholders or []),
            )
            for item in session_state.file_roles
            if travels(item)
        ),
        None,
    )
    if (
        runtime_input is None
        and result_type is None
        and contract is None
        and template is None
    ):
        return None
    return RunPreviewPayload(
        runtime_input=runtime_input,
        max_files=session_state.mapped_file_limit.accepted_value,
        result_type=result_type,
        report_layout=commit.report_disposition if commit is not None else None,
        required_sections=list(contract.required_sections) if contract else [],
        obligations=list(contract.secondary_obligations) if contract else [],
        template=template,
    )


def _attachment_assumption(
    item: FileRoleEvidence,
    locale: Locale,
    *,
    render_value: RenderEvidenceValue,
    travels: bool,
) -> str:
    role = _attachment_role_label(item.role, locale)
    coverage = _attachment_coverage_description(
        item.coverage,
        has_readable_text=item.has_readable_text,
        locale=locale,
    )
    filename = render_value(item.filename)
    # Two uploads can share a filename — or a clipped filename — while
    # carrying different roles and different template placeholders, so the
    # file's own identity is part of what the user attests to. A prefix is a
    # label, not an identity, so the whole id is disclosed.
    reference = str(item.file_id)
    placeholders = _template_placeholder_text(item, locale, render_value=render_value)
    consequence = _attachment_run_consequence(travels, locale)
    if locale == "sv":
        readable = "ja" if item.has_readable_text else "nej"
        return (
            f'{_ATTACHMENT_ASSUMPTION_PREFIX_SV}Bilaga "{filename}" (#{reference}): '
            f"vald roll {role}; läsbar text: {readable}; "
            f"täckning: {coverage}. {consequence}{placeholders}"
        )
    readable = "yes" if item.has_readable_text else "no"
    return (
        f'{_ATTACHMENT_ASSUMPTION_PREFIX_EN}Attachment "{filename}" (#{reference}): '
        f"selected role {role}; "
        f"readable text: {readable}; coverage: {coverage}. {consequence}{placeholders}"
    )


def _attachment_run_consequence(travels: bool, locale: Locale) -> str:
    """What the attachment means for runs, read from the committed architecture.

    A role label is evidence about the file; whether the file travels with the
    flow is decided by the commit. What a run receives is the input contract's
    business.
    """

    if travels:
        return (
            "Mallen följer med flödet och fylls i vid varje körning."
            if locale == "sv"
            else "The template travels with the flow and is filled at every run."
        )
    return (
        "Filen följer inte med i körningar; vad varje körning får in styrs av "
        "indatakontraktet ovan."
        if locale == "sv"
        else "This file is not carried into runs; what each run receives follows "
        "the input contract above."
    )


def _template_placeholder_text(
    item: FileRoleEvidence,
    locale: Locale,
    *,
    render_value: RenderEvidenceValue,
) -> str:
    """Template placeholders compile into runtime fields, so they are disclosed."""

    if item.template_placeholders is None:
        return ""
    if not item.template_placeholders:
        return (
            " Inga platshållare hittades."
            if locale == "sv"
            else " No placeholders were found."
        )
    rendered = ", ".join(
        render_value(placeholder) for placeholder in item.template_placeholders
    )
    return (
        f" Platshållare: {rendered}."
        if locale == "sv"
        else f" Placeholders: {rendered}."
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


def _schema_summary_lines(
    session_state: PlanningState,
    locale: Locale,
    *,
    render_value: RenderEvidenceValue,
    is_edit_mode: bool,
    include_named_content_details: bool,
) -> list[str]:
    lines: list[str] = []
    input_evidence = session_state.input_schema_evidence
    if input_evidence is not None:
        field_text = _schema_field_text(
            input_evidence, locale, render_value=render_value
        )
        identity = _schema_identity_text(input_evidence)
        lines.append(
            (
                "Ett uttryckligt indataschema har valts för flödets strukturerade indata. "
                f"{identity} Valda fält: {field_text}."
            )
            if locale == "sv"
            else (
                "An explicit input schema is selected for the flow's structured input. "
                f"{identity} Selected fields: {field_text}."
            )
        )
    named_result_line = _named_result_summary_line(
        session_state,
        locale,
        render_value=render_value,
        is_edit_mode=is_edit_mode,
        include_details=include_named_content_details,
    )
    if named_result_line is not None:
        lines.append(named_result_line)
    output_line = _output_schema_summary_line(
        session_state, locale, render_value=render_value
    )
    if output_line is not None:
        lines.append(output_line)
    return lines


def _named_result_summary_line(
    session_state: PlanningState,
    locale: Locale,
    *,
    render_value: RenderEvidenceValue,
    is_edit_mode: bool,
    include_details: bool,
) -> str | None:
    # Every obligation with the shape the user wrote next to it. The old line
    # showed eight bare names and then claimed structure was not fixed, which
    # contradicted the declared shapes this state already persists.
    obligations = session_state.named_result_evidence
    if not obligations:
        return None
    projection = named_result_projection(session_state, is_edit_mode=is_edit_mode)
    if not include_details:
        if projection is None:
            return None
        if locale == "sv":
            return (
                "De namngivna delarna byggs på översta nivån, sida vid sida. "
                "Bifoga ett uttryckligt utdataschema om någon del ska ligga inuti "
                "en annan."
            )
        return (
            "The named content is built at the top level, side by side. Attach "
            "an explicit output schema if any part belongs inside another."
        )
    names = ", ".join(
        _named_result_text(obligation, locale, render_value=render_value)
        for obligation in obligations
    )
    if locale == "sv":
        preserved = (
            f"Användaren har namngett innehåll som slutresultatet ska bevara: {names}."
        )
    else:
        preserved = (
            f"The user named content that the final result must preserve: {names}."
        )
    if projection is None:
        # No attested contract is in force — an edit has no create contract
        # to verify, an exact declared schema owns the shape, or this is not
        # a structured result at all — so describing flat placement would
        # describe something that is not happening. The confirmation is
        # hashed, so a sentence that does not apply would be attested to as
        # if it did.
        return preserved
    # The placement limitation belongs here, not in a later error: these fields
    # are built side by side at the top level, so a user who described one
    # field as living inside another sees that before confirming, together with
    # the one way to get the hierarchy they asked for.
    if locale == "sv":
        return (
            f"{preserved} Varje fält byggs på översta nivån, sida vid sida. "
            "Bifoga ett uttryckligt utdataschema om något fält ska ligga inuti "
            "ett annat."
        )
    return (
        f"{preserved} Each field is built at the top level, side by side. Attach "
        "an explicit output schema if a field belongs inside another."
    )


def _named_result_text(
    obligation: NamedResultEvidence,
    locale: Locale,
    *,
    render_value: RenderEvidenceValue,
    include_placement: bool = True,
) -> str:
    name = render_value(obligation.name)
    details: list[str] = []
    match obligation.declared_shape:
        case "array":
            details.append(
                "användaren skrev en lista"
                if locale == "sv"
                else "the user wrote a list"
            )
        case "object":
            details.append(
                "användaren skrev ett objekt"
                if locale == "sv"
                else "the user wrote an object"
            )
        case None:
            pass
        case _ as unreachable:
            assert_never(unreachable)

    indentation = ""
    if include_placement:
        match obligation.placement:
            case ExactNamedResultPlacement(segments=segments) if segments:
                indentation = "\N{NO-BREAK SPACE}\N{NO-BREAK SPACE}" * len(segments)
                parent_path = " › ".join(render_value(segment) for segment in segments)
                details.append(f"under {parent_path}")
                name = f"↳ {name}"
            case ExactNamedResultPlacement():
                pass
            case UnplacedNamedResultPlacement():
                details.append(
                    "plats ej angiven" if locale == "sv" else "placement not specified"
                )
            case _ as unreachable:
                assert_never(unreachable)

    suffix = f" ({'; '.join(details)})" if details else ""
    return f"{indentation}{name}{suffix}"


def _output_schema_summary_line(
    session_state: PlanningState,
    locale: Locale,
    *,
    render_value: RenderEvidenceValue,
) -> str | None:
    evidence = session_state.output_schema_evidence
    if evidence is None:
        return None
    field_text = _schema_field_text(evidence, locale, render_value=render_value)
    identity = _schema_identity_text(evidence)
    if evidence.source == "template_placeholders":
        if not evidence.truncated or evidence.total_count is None:
            return None
        projection = project_schema_fields(evidence.json_schema)
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
    terminal_output = session_state.resolved_slots.get("terminal_output")
    if terminal_output is None or terminal_output.value != "structured_json":
        return None
    if evidence.strength == "explicit":
        if locale == "sv":
            return (
                "Ett uttryckligt utdataschema styr JSON-resultatet. "
                f"{identity} Valda fält: {field_text}."
            )
        return (
            "An explicit output schema controls the JSON result. "
            f"{identity} Selected fields: {field_text}."
        )
    if locale == "sv":
        return (
            "En försiktig utdatastruktur har härletts från valt exempelresultat; "
            "den är vägledning och inte ett uttryckligt slutet kontrakt. "
            f"{identity} Härledda fält: {field_text}."
        )
    return (
        "A conservative output shape was inferred from the selected example; "
        "it is guidance, not an explicit closed contract. "
        f"{identity} Inferred fields: {field_text}."
    )


def _schema_identity_text(evidence: SchemaEvidence) -> str:
    """Which schema, not just how it renders.

    Two candidate schemas can project the same visible head, so the
    fingerprint is what actually distinguishes the one the flow will use.
    """

    return f"Schema {evidence.fingerprint} ({evidence.source}, {evidence.strength})."


def _schema_field_text(
    evidence: SchemaEvidence,
    locale: Locale,
    *,
    render_value: RenderEvidenceValue,
) -> str:
    projection = project_schema_fields(evidence.json_schema)
    text = _bounded_projection_text(
        projection.fields, locale=locale, render_value=render_value
    )
    if not projection.truncated:
        return text
    omitted = projection.total_count - len(projection.fields)
    return (
        f"{text} (+{omitted} av {projection.total_count})"
        if locale == "sv"
        else f"{text} (+{omitted} of {projection.total_count})"
    )


def _bounded_projection_text(
    fields: tuple[str, ...],
    *,
    locale: Locale,
    render_value: RenderEvidenceValue,
) -> str:
    if fields:
        return ", ".join(render_value(field) for field in fields)
    return (
        "inga namngivna toppnivåfält" if locale == "sv" else "no named top-level fields"
    )


def _example_output_assumptions(
    session_state: PlanningState,
    locale: Locale,
    *,
    render_value: RenderEvidenceValue,
) -> list[str]:
    constraints = session_state.example_output_constraints
    if constraints is None:
        return []
    # Every heading and every style constraint: all headings reach proposal
    # preparation, so heading nine could change the plan while the user saw
    # only "(+1)".
    headings = constraints.headings
    styles = constraints.style_constraints
    assumptions: list[str] = []
    if headings:
        rendered = ", ".join(render_value(heading) for heading in headings)
        assumptions.append(
            f"Exempelresultatets valda rubriker: {rendered}."
            if locale == "sv"
            else f"Selected example-output headings: {rendered}."
        )
    if styles:
        rendered = "; ".join(
            f"{item.category}: {render_value(item.description)}" for item in styles
        )
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


def _settling_question_id(slot_name: str, slot: ResolvedSlot) -> str | None:
    """The question a reader can be sent back to for this decision.

    A structured answer is the only slot provenance that came from a question,
    and slots are keyed by the canonical question id, so the catalog decides
    whether that question can be put again. A slot the catalog does not hold
    would be a link to nowhere, and the mixed-material phrasing settles the
    same canonical question, so the canonical id is what travels.
    """

    if slot.source != "structured_answer" or slot_name not in QUESTION_CATALOG:
        return None
    return slot_name


def _slot_is_key_decision(slot: ResolvedSlot) -> bool:
    match slot.source:
        case "structured_answer" | "flow_default":
            return True
        case "requirements_summary":
            # Confirming a disclosure must not change that disclosure. This
            # provenance is created *by* the confirmation, so promoting the
            # fact from an assumption to a key decision here hashes a
            # different record and asks the user to attest to the same
            # requirements again — the loop that ran sessions into the
            # interaction limit. How the user answered is provenance, not a
            # different requirement.
            return False
        case "model":
            # The bucket follows the same boundary as attestation precedence:
            # acceptance regrades any classification it outranks, and a regraded
            # fact reads as an assumption, so a classification acceptance would
            # regrade has to read as one already. High confidence is what
            # survives acceptance; an explicit reading is what earns the
            # stronger presentation.
            return slot.confidence == "high" and slot.evidence_level == "explicit"
        case "attachment_structure" | "policy_default" | "heuristic":
            return False
    return assert_never(slot.source)


def _slot_assumption(
    slot_name: str,
    slot: ResolvedSlot,
    locale: Locale,
) -> str:
    return (
        f"{render_summary_label(slot_name, locale)}: "
        f"{_slot_value_for_slot(slot_name, slot.value, locale)}"
    )


def _in_sentence(label: str) -> str:
    """Lower the first letter of a label unless it opens with an acronym."""

    if len(label) >= 2 and label[:2].isupper():
        return label
    return label[:1].lower() + label[1:]


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
        # Option labels are title-cased for the option list; inside a sentence
        # they read as nouns, so they drop the capital unless they open with
        # an acronym ("PDF-dokument").
        if locale == "sv":
            summary = (
                f"Flödet tar emot {_in_sentence(runtime_input or 'indata')} vid "
                f"körning och levererar "
                f"{_in_sentence(terminal_output or 'ett slutresultat')}."
            )
            if post_processing_goal:
                summary += f" Syftet med bearbetningen: {post_processing_goal}."
            return summary
        summary = (
            f"The flow accepts {_in_sentence(runtime_input or 'runtime input')} at "
            f"runtime and delivers {_in_sentence(terminal_output or 'a final result')}."
        )
        if post_processing_goal:
            summary += f" Purpose of the processing: {post_processing_goal}."
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
    # A document report is built with the layout the commit carries, so the
    # card says that; any other shape says whether many inputs collapse into
    # one result or stay separate. Both come from the commit, never from a
    # reading the compiler will not see.
    if commit.report_disposition is not None:
        multiplicity = _report_layout_summary(commit.report_disposition, locale)
    elif locale == "sv":
        multiplicity = (
            "en gemensam sammanställning"
            if commit.aggregation_intent == "aggregate"
            else "ett resultat per underlag"
        )
    else:
        multiplicity = (
            "one combined result"
            if commit.aggregation_intent == "aggregate"
            else "one result per source"
        )
    chain = " → ".join(steps)
    return KeyDecisionPayload(topic=topic, decision=f"{chain} ({multiplicity})")


def _report_layout_summary(layout: str, locale: Locale) -> str:
    if locale == "sv":
        return {
            "per_source_sections": "ett avsnitt per underlag",
            "synthesized_overview": "en samlad sammanställning",
            "both": "ett avsnitt per underlag och en samlad sammanställning",
        }[layout]
    return {
        "per_source_sections": "one section per source",
        "synthesized_overview": "one combined result",
        "both": "one section per source and one combined result",
    }[layout]


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


__all__ = [
    "build_requirements_disclosure",
    "resolve_locale",
]
