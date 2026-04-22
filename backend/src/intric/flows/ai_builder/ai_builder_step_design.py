"""Structured step-design rules surfaced to the planner.

Each `StepDesignSection` groups one heading plus an ordered tuple of
`StepDesignRule` bullets (with optional nested sub-rules). The renderer
turns the registry into the markdown block that lands in the
create-proposal system prompt.

The registry replaces the hand-prose `_KNOWLEDGE_PACK_CREATE_STEP_DESIGN`
constant: structuring the data lets future consumers (e.g. a validator
that wants to cite a rule-id, a prompt-mode renderer that wants a
different section ordering) read the same source instead of the
renderer copying prose by hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class StepDesignRule:
    """One planner-facing rule bullet with optional nested sub-rules.

    Frozen + slotted: entries are canonical and must not mutate after
    construction, mirroring the discipline applied to `Pattern` and
    `ValidationRepairExample`.
    """

    text: str
    sub_rules: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StepDesignSection:
    """One heading plus the ordered bullets that belong under it."""

    heading: str
    rules: tuple[StepDesignRule, ...] = field(default_factory=tuple)


STEP_DESIGN_SECTIONS: tuple[StepDesignSection, ...] = (
    StepDesignSection(
        heading="Instruktioner",
        rules=(
            StepDesignRule(
                text=(
                    "`instructions` ska vara ren uppgiftsbeskrivning — inga "
                    "`{{ ... }}`-variabler"
                )
            ),
            StepDesignRule(text="Beskriv roll, krav, format och begränsningar tydligt"),
            StepDesignRule(
                text=(
                    "Backend kompilerar underlaget från `input_source`, tidigare "
                    "steg och formulärfält"
                )
            ),
            StepDesignRule(
                text=(
                    "Backend kompilerar även explicita fältbindningar från "
                    "`uses_previous_fields`"
                )
            ),
            StepDesignRule(
                text=(
                    "Instruktioner får gärna vara LÅNGA och detaljerade när "
                    "uppgiften kräver flera regler, formatkrav eller beslutslogik"
                )
            ),
        ),
    ),
    StepDesignSection(
        heading="JSON-utdata via `output_fields`",
        rules=(
            StepDesignRule(
                text='`output_fields` används bara för `output_type="json"`'
            ),
            StepDesignRule(
                text="Max nesting depth 3: toppnivåfält, barnfält och ett barnbarnsled"
            ),
            StepDesignRule(
                text="Bra mönster:",
                sub_rules=(
                    "objekt med scalar-fält",
                    "array med objektposter",
                    "objekt/array som innehåller ett extra lager scalar-fält",
                ),
            ),
            StepDesignRule(
                text="Undvik djupare träd än så; platta hellre ut strukturen"
            ),
        ),
    ),
    StepDesignSection(
        heading="Formulär och runtime",
        rules=(
            StepDesignRule(
                text=(
                    "Modellera användarens körningsdata som `form_fields` i "
                    "stället för dold prompttext"
                )
            ),
            StepDesignRule(text="Referera till dessa med `uses_form_fields`"),
            StepDesignRule(
                text=(
                    "När ett senare steg bara behöver vissa JSON-fält från ett "
                    "tidigare steg: använd `uses_previous_fields`"
                )
            ),
            StepDesignRule(
                text=(
                    "Om användaren måste ladda upp filer vid körning: sätt "
                    "`runtime_upload=true`"
                )
            ),
        ),
    ),
    StepDesignSection(
        heading="Dokumentleverans",
        rules=(
            StepDesignRule(
                text=(
                    '`document_delivery_mode="generated"` för vanliga genererade '
                    "PDF/DOCX-dokument"
                )
            ),
            StepDesignRule(
                text='`document_delivery_mode="template_fill"` bara för DOCX'
            ),
        ),
    ),
)


_HEADER = "# Create-läge: kompilerad datamodell"


def render_step_design() -> str:
    """Render the step-design reference section for the create-proposal prompt.

    Output order matches `STEP_DESIGN_SECTIONS` and each section's
    declared rule order. Nested sub-rules indent one extra level under
    their parent bullet.
    """
    lines: list[str] = [_HEADER]
    for section in STEP_DESIGN_SECTIONS:
        lines.append("")
        lines.append(f"## {section.heading}")
        for rule in section.rules:
            lines.append(f"- {rule.text}")
            for sub in rule.sub_rules:
                lines.append(f"  - {sub}")
    return "\n".join(lines)


__all__ = [
    "STEP_DESIGN_SECTIONS",
    "StepDesignRule",
    "StepDesignSection",
    "render_step_design",
]
