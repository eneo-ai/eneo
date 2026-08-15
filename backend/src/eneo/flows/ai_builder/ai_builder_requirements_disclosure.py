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

from eneo.flows.ai_builder.ai_builder_attachment_context import (
    render_ai_builder_evidence_value,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    KeyDecisionPayload,
    RequirementsDisclosureContent,
    RequirementsSummaryPayload,
    ResolvedRequirementPayload,
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
)
from eneo.flows.ai_builder.ai_builder_schema_evidence import project_schema_fields
from eneo.flows.ai_builder.planning_state import (
    AttachmentCoverage,
    CheckpointIntent,
    CheckpointProducerKind,
    ConfirmedRuntimeMetadataField,
    ExampleOutputSchemaInferenceReason,
    FileRole,
    FileRoleEvidence,
    NamedResultEvidence,
    PlanningState,
    ResolvedSlot,
    SchemaEvidence,
)
from eneo.flows.ai_builder.question_catalog import (
    QUESTION_CATALOG,
    Locale,
    legal_slot_values,
    render_question,
    render_summary_label,
)
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
    discovery_assumptions: tuple[str, ...] = (),
) -> RequirementsSummaryPayload:
    """Render the complete disclosure and stamp the version that hashes it."""

    locale = resolve_locale(ui_language)
    identity = _disclosure_content(
        session_state,
        locale,
        discovery_assumptions,
        render_value=_whole_evidence_value,
    )
    display = _disclosure_content(
        session_state,
        locale,
        discovery_assumptions,
        render_value=render_ai_builder_evidence_value,
    )
    return RequirementsSummaryPayload(
        **display.model_dump(),
        requirements_version=build_requirements_version(identity),
    )


def _disclosure_content(
    session_state: PlanningState,
    locale: Locale,
    discovery_assumptions: tuple[str, ...],
    *,
    render_value: RenderEvidenceValue,
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
        session_state, locale, render_value=render_value
    )
    if schema_summary_lines:
        summary = f"{summary} {' '.join(schema_summary_lines)}"
    return RequirementsDisclosureContent(
        summary=summary,
        key_decisions=key_decisions,
        input_description=input_description,
        output_description=output_description,
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
            ],
            *discovery_assumptions,
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
    label = render_value(field.value.label)
    name = render_value(field.value.variable_name)
    required = (
        ("obligatoriskt" if field.value.required else "valfritt")
        if locale == "sv"
        else ("required" if field.value.required else "optional")
    )
    return f"{label} ({name}, {field.value.field_type}, {required})"


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
    obligations = _signal_values(
        session_state, RESULT_OBLIGATION_SIGNAL_ID, render_value=render_value
    )
    if obligations:
        assumptions.append(
            f"Ytterligare krav på slutresultatet: {obligations}."
            if locale == "sv"
            else f"Additional obligations on the final result: {obligations}."
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
    return [
        _attachment_assumption(item, locale, render_value=render_value)
        for item in ordered
    ]


def _attachment_assumption(
    item: FileRoleEvidence,
    locale: Locale,
    *,
    render_value: RenderEvidenceValue,
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
    if locale == "sv":
        readable = "ja" if item.has_readable_text else "nej"
        return (
            f'{_ATTACHMENT_ASSUMPTION_PREFIX_SV}Bilaga "{filename}" (#{reference}): '
            f"vald roll {role}; läsbar text: {readable}; "
            f"täckning: {coverage}.{placeholders}"
        )
    readable = "yes" if item.has_readable_text else "no"
    return (
        f'{_ATTACHMENT_ASSUMPTION_PREFIX_EN}Attachment "{filename}" (#{reference}): '
        f"selected role {role}; "
        f"readable text: {readable}; coverage: {coverage}.{placeholders}"
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
        session_state, locale, render_value=render_value
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
) -> str | None:
    # Every obligation with the shape the user wrote next to it. The old line
    # showed eight bare names and then claimed structure was not fixed, which
    # contradicted the declared shapes this state already persists.
    obligations = session_state.named_result_evidence
    if not obligations:
        return None
    names = ", ".join(
        _named_result_text(obligation, locale, render_value=render_value)
        for obligation in obligations
    )
    if locale == "sv":
        return (
            f"Användaren har namngett innehåll som slutresultatet ska bevara: {names}."
        )
    return f"The user named content that the final result must preserve: {names}."


def _named_result_text(
    obligation: NamedResultEvidence,
    locale: Locale,
    *,
    render_value: RenderEvidenceValue,
) -> str:
    name = render_value(obligation.name)
    match obligation.declared_shape:
        case "array":
            return (
                f"{name} (användaren skrev en lista)"
                if locale == "sv"
                else f"{name} (the user wrote a list)"
            )
        case "object":
            return (
                f"{name} (användaren skrev ett objekt)"
                if locale == "sv"
                else f"{name} (the user wrote an object)"
            )
        case None:
            return name
    return assert_never(obligation.declared_shape)


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


def _slot_is_key_decision(slot: ResolvedSlot) -> bool:
    match slot.source:
        case "structured_answer" | "requirements_summary" | "flow_default":
            return True
        case "model":
            return slot.evidence_level == "explicit" and slot.is_commit_grade
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
    # The aggregation intent decides whether many inputs collapse into one
    # result or stay separate, so it belongs to the disclosed architecture.
    aggregation = (
        (
            "en gemensam sammanställning"
            if commit.aggregation_intent == "aggregate"
            else "ett resultat per underlag"
        )
        if locale == "sv"
        else (
            "one combined result"
            if commit.aggregation_intent == "aggregate"
            else "one result per source"
        )
    )
    chain = " → ".join(steps)
    return KeyDecisionPayload(topic=topic, decision=f"{chain} ({aggregation})")


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
