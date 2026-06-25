from __future__ import annotations

from intric.flows.ai_builder.ai_builder_critic_invariants import CriticIssue
from intric.flows.ai_builder.ai_builder_feedback_formatting import (
    format_revision_feedback,
)

# Raw critic remediations stay mechanics-oriented for edit/compiled contexts.
# Create mode translates them here because propose_flow only accepts semantic create steps.
CREATE_CRITIC_REMEDIATION: dict[str, str] = {
    "runtime_metadata_requires_form_fields": (
        "Beskriv vilka extra inmatningsfält användaren ska fylla i vid körning och vilka semantiska steg som behöver värdena."
    ),
    "sectioned_form_intake_requires_form_fields": (
        "Beskriv varje rubrik eller sektion som ett eget inmatningsfält och låt senare semantiska steg använda dessa värden för slutresultatet."
    ),
    "rich_workflow_requires_form_fields": (
        "Lägg till de manuella kompletteringarna som namngivna inmatningsfält i intentionen och beskriv vilka steg som behöver dem."
    ),
    "rich_workflow_requires_json_contract_step": (
        'Lägg till ett mellanliggande extraktionssteg med output_type="json" och output_fields med namngivna fält innan analys, rapport eller dokumentleverans.'
    ),
    "rich_workflow_requires_multiple_steps": (
        "Dela upp arbetsflödet i tydliga semantiska steg för extraktion, analys eller granskning innan slutleveransen."
    ),
    "structured_extraction_requires_json_contract_step": (
        'Lägg till ett tydligt extraktionssteg med output_type="json" och output_fields med namngivna fält som senare steg kan återanvända.'
    ),
    "explicit_json_contract_request_without_step": (
        "Lägg till ett strukturerat extraktionssteg när användaren ber om fält, kontrakt eller maskinellt återanvändbar information."
    ),
    "action_followup_requires_followup_fields": (
        "Beskriv ett semantiskt uppföljningsresultat som håller isär beslut, åtgärder eller nästa steg, ansvariga, deadlines och öppna frågor."
    ),
    "field_reuse_requires_input_bindings": (
        "Beskriv vilka namngivna fält från den strukturerade extraktionen som nästa semantiska steg ska återanvända."
    ),
    "prefer_targeted_underlag_over_all_previous_steps": (
        "Beskriv ett semantiskt syntessteg som sammanställer just de relevanta strukturerade resultaten från tidigare steg, i stället för att läsa allt tidigare innehåll."
    ),
    "final_assembler_must_reference_explicit_section_outputs": (
        "Beskriv slutsteget som ett semantiskt sammansättningssteg som använder de relevanta strukturerade avsnittstexterna från tidigare steg explicit, i stället för att läsa allt tidigare innehåll."
    ),
    "terminal_renderer_must_consume_previous_composer": (
        "Låt det terminala DOCX/PDF-steget endast rendera den färdiga texten från föregående semantiska steg, inte läsa alla tidigare strukturerade steg igen."
    ),
    "terminal_renderer_must_not_consume_review_only_step": (
        "Lägg inte ett granskningssteg som bara producerar anteckningar direkt före DOCX/PDF. Sista textsteget före renderern ska vara den färdiga dokumenttexten: flytta granskningen före slutlig sammanställning, eller låt granskningssteget skriva en reviderad slutversion av hela dokumentet."
    ),
    "section_text_steps_must_reference_source_json_fields": (
        "Låt varje avsnittssteg beskriva vilka namngivna fält från den strukturerade extraktionen som behövs för just det avsnittet, så att varje rubrik får relevant underlag utan att läsa allt tidigare innehåll."
    ),
    "requested_output_sections_require_section_writers": (
        "Bevara användarens namngivna rapportavsnitt som tydliga semantiska skrivsteg i intentionen, och gruppera bara närliggande rubriker när det behövs."
    ),
    "redundant_terminal_json_format_tail_after_final_text_composer": (
        "Ta bort det extra JSON-formatsteget efter sluttexten när användaren inte har valt JSON som slutformat. Låt det semantiska textsteget som skriver slutversionen vara terminalt."
    ),
    "final_text_step_must_reference_relevant_structured_outputs": (
        "Beskriv ett semantiskt kompositionssteg som väver in relevanta strukturerade resultat från flera tidigare steg, inte bara det senaste."
    ),
    "form_fields_declared_must_be_referenced": (
        "Koppla varje deklarerat inmatningsfält till minst ett semantiskt steg som faktiskt behöver värdet, eller ta bort fältet från planen."
    ),
    "simple_text_transform_must_remain_single_step": (
        "För en direkt textomvandling utan filer, JSON, extra fält eller granskning ska intentionen innehålla ett enda textsteg som gör omvandlingen."
    ),
}
CREATE_CRITIC_REMEDIATION_PASSTHROUGH_IDS: frozenset[str] = frozenset(
    {"mcp_selection_requires_semantic_support"}
)


def format_create_quality_feedback(feedback: str | None) -> str | None:
    if feedback is None:
        return None

    normalized_feedback = feedback.casefold()
    repair_rules: list[str] = []
    if (
        "valt docx som slutartefakt" in normalized_feedback
        and "producerar inte docx" in normalized_feedback
    ):
        repair_rules.append(
            "Set the final step output_type to 'docx' so the last step matches the requested final artifact."
        )
    if (
        "valt pdf som slutartefakt" in normalized_feedback
        and "producerar inte pdf" in normalized_feedback
    ):
        repair_rules.append(
            "Set the final step output_type to 'pdf' so the last step matches the requested final artifact."
        )
    if not repair_rules:
        return feedback
    return f"{feedback}\n\nCreate-intent quality repair rules:\n- " + "\n- ".join(
        repair_rules
    )


def format_create_intent_quality_feedback(feedback: str | None) -> str | None:
    if feedback is None:
        return None

    intent_feedback = feedback.replace("output_contract", "output_fields")
    normalized_feedback = intent_feedback.casefold()
    repair_rules: list[str] = []
    if "output_type 'json'" in normalized_feedback and "output_fields" in (
        normalized_feedback
    ):
        repair_rules.append(
            "For every JSON semantic step that feeds later steps, set output_fields with named fields that match the step's extracted data."
        )

    formatted = format_create_quality_feedback(intent_feedback)
    if not repair_rules:
        return formatted
    return f"{formatted}\n\nCreate-intent schema repair rules:\n- " + "\n- ".join(
        repair_rules
    )


def format_create_critic_feedback(issues: tuple[CriticIssue, ...]) -> str | None:
    remediations: list[str] = []
    for issue in issues:
        if issue.kind != "semantic":
            raise ValueError(
                f"Create critic feedback requires semantic issues; received {issue.id}"
            )
        if issue.id in CREATE_CRITIC_REMEDIATION:
            remediations.append(CREATE_CRITIC_REMEDIATION[issue.id])
            continue
        if issue.id in CREATE_CRITIC_REMEDIATION_PASSTHROUGH_IDS:
            remediations.append(issue.remediation)
            continue
        raise ValueError(f"No create-mode critic remediation registered for {issue.id}")

    if not remediations:
        return None
    return format_revision_feedback("Quality issues", remediations)
