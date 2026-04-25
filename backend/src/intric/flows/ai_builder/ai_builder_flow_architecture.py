"""Structured create-outline rules surfaced to the planner.

Each `FlowArchitectureSection` groups one heading plus an ordered tuple
of bullet-rule strings. The renderer turns the registry (plus a short
lead paragraph describing the create-mode outline contract) into the
markdown block that lands in the create-proposal system prompt.

The registry replaces older hand-prose full-mechanics guidance.
Structuring the data lets
future consumers (e.g. a validator that wants to cite a specific
planner-responsibility rule, a prompt-mode renderer that wants a
different section ordering) read the same source instead of the
renderer copying prose by hand.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FlowArchitectureSection:
    """One heading plus the ordered bullet-rule strings under it.

    Frozen + slotted: entries are canonical and must not mutate after
    construction, mirroring the discipline applied to
    `StepDesignSection` and `ValidationRepairExample`.
    """

    heading: str
    rules: tuple[str, ...]


FLOW_ARCHITECTURE_SECTIONS: tuple[FlowArchitectureSection, ...] = (
    FlowArchitectureSection(
        heading="Vad modellen anger",
        rules=(
            "`flow_name`, `flow_description` och `plan_rationale` som vanlig text",
            (
                "`runtime_input` beskriver bara huvudingången vid körning "
                "(`text`, `json`, `document`, `file` eller `audio`)"
            ),
            (
                "`input_fields` modellerar sekundära inmatningsfält/input variables "
                "som användaren fyller i vid sidan av huvudunderlaget"
            ),
            "`steps[].name` och `steps[].task` beskriver semantiska arbetssteg",
            (
                "`steps[].output_fields` används när ett steg ska producera "
                "strukturerade datapunkter för senare arbete"
            ),
            "`steps[].uses_input_fields` refererar till namn i `input_fields`",
            "`final_output_type` anger slutartefakten (`text`, `json`, `pdf` eller `docx`)",
        ),
    ),
    FlowArchitectureSection(
        heading="Vad backend äger",
        rules=(
            "input source/type och upload/runtime config",
            "`underlag` / input bindings och variabelinjektion mellan steg",
            "stegrefar (`plan_step_ref`)",
            "`output_mode`",
            "`document_delivery_mode` för PDF/DOCX-leverans",
            "`uses_previous_fields` och fältnivåreferenser mellan JSON-steg",
            "kontrakt / JSON Schema från `output_fields`",
        ),
    ),
    FlowArchitectureSection(
        heading="Praktiska regler",
        rules=(
            "Skriv inga template-variabler som `{{ ... }}` i outline-fält",
            "Skriv inga ID:n, hashvärden, tidsstämplar, råa bindings eller rå JSON Schema",
            "Använd flera tydliga steg för komplexa flöden i stället för ett överlastat steg",
            (
                "Lägg körningsmetadata som ska återanvändas i `input_fields`, "
                "inte gömt i prompttext"
            ),
            (
                "Lägg inte huvudtexten, dokumentet, filen eller ljudet som ett "
                "`input_field`; backend kopplar huvudingången från arkitekturen"
            ),
            (
                "Använd `output_fields` när senare steg behöver stabila fält; "
                "backend gör steget strukturerat"
            ),
            (
                "Beskriv syntes/jämförelse semantiskt; backend avgör när flera "
                "tidigare steg ska kopplas in som källa"
            ),
            (
                "För DOCX/PDF räcker `final_output_type`; backend skapar leveranssteget "
                "eller dokumentläget"
            ),
            (
                "Citations kan begäras bara som semantisk önskan på textsteg; "
                "backend validerar om det stöds"
            ),
        ),
    ),
)


_HEADER = "# Outline-flow-kompilering"
_LEAD = (
    "I create-läge beskriver modellen bara avsikten i `outline_flow`. "
    "Backend kompilerar outline till kanonisk flödesspecifikation."
)


def render_flow_architecture() -> str:
    """Render the flow-architecture reference section for the create-proposal prompt.

    Output order matches `FLOW_ARCHITECTURE_SECTIONS` and each section's
    declared rule order. The header and lead paragraph precede the
    first section.
    """
    lines: list[str] = [_HEADER, "", _LEAD]
    for section in FLOW_ARCHITECTURE_SECTIONS:
        lines.append("")
        lines.append(f"## {section.heading}")
        for rule in section.rules:
            lines.append(f"- {rule}")
    return "\n".join(lines)


__all__ = [
    "FLOW_ARCHITECTURE_SECTIONS",
    "FlowArchitectureSection",
    "render_flow_architecture",
]
