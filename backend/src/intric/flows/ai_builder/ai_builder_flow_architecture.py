"""Structured flow-architecture rules surfaced to the planner.

Each `FlowArchitectureSection` groups one heading plus an ordered tuple
of bullet-rule strings. The renderer turns the registry (plus a short
lead paragraph describing the create-mode contract) into the markdown
block that lands in the create-proposal system prompt.

The registry replaces the hand-prose
`_KNOWLEDGE_PACK_CREATE_FLOW_ARCHITECTURE` constant: structuring the
data lets future consumers (e.g. a validator that wants to cite a
specific planner-responsibility rule, a prompt-mode renderer that wants
a different section ordering) read the same source instead of the
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
        heading="Vad du SKA ange",
        rules=(
            "`instructions` — vanlig text utan variabelsyntax",
            "`input_source`, `input_type`, `output_type`",
            (
                "`runtime_upload`, `runtime_required`, `runtime_max_files` "
                "för första uppladdningssteget"
            ),
            "`uses_form_fields` när senare steg behöver formulärvärden",
            (
                "`uses_previous_fields` när senare steg behöver specifika "
                "strukturerade fält från tidigare JSON-steg"
            ),
            "`document_delivery_mode` för PDF/DOCX-leverans",
            "`citations_requested` för textsteg som ska ha källhänvisningar",
            "`output_fields` för JSON-steg",
        ),
    ),
    FlowArchitectureSection(
        heading="Vad backend äger",
        rules=(
            "stegrefar (`plan_step_ref`)",
            "underlag / variabelinjektion mellan steg",
            "kontrakt / JSON Schema",
            "`output_mode`",
            "runtime-input-config",
        ),
    ),
    FlowArchitectureSection(
        heading="Praktiska regler",
        rules=(
            'Steg 1 MÅSTE använda `input_source="flow_input"`',
            (
                'Senare steg får inte använda `input_source="flow_input"`; '
                "använd `previous_step` eller `all_previous_steps`"
            ),
            (
                "Sista steget MÅSTE ha `output_type` som matchar den explicit "
                "efterfrågade slutartefakten (`text`, `json`, `pdf` eller `docx`)"
            ),
            (
                "När flera uppladdade dokument ska vägas samman i en gemensam "
                "analys eller grounded sammanfattning ska ett samlande steg "
                'använda `input_source="all_previous_steps"`'
            ),
            (
                "Varje objekt i `steps` måste vara ett komplett steg. "
                "Fältdefinitioner med `name`, `field_type`, `description` och "
                "`required` hör hemma i `output_fields`, inte som egna poster "
                "i `steps`"
            ),
            (
                "Filuppladdning används via `runtime_upload=true` på ett "
                "`flow_input`-steg med `input_type=document`, `file` eller "
                "`audio`"
            ),
            (
                'Använd `output_type="json"` + `output_fields` när nästa steg '
                "behöver namngivna datapunkter"
            ),
            (
                'Använd `output_type="text"` för grounded sammanfattningar, '
                "resonemang och läsbar rapporttext"
            ),
            (
                'Använd `output_type="docx"` eller `"pdf"` bara när steget '
                "faktiskt levererar dokumentet"
            ),
        ),
    ),
)


_HEADER = "# Create-flow-kompilering"
_LEAD = (
    "I create-läge beskriver du bara avsikten i `create_flow`. "
    "Backend kompilerar utkastet till den kanoniska flödesspecifikationen."
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
