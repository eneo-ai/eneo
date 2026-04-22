"""Structured validation-repair examples surfaced to the planner.

Each `ValidationRepairExample` names one validator-rejected draft, the
exact error message the validator emits, and the corrected draft the
planner should produce instead. The renderer turns the registry into the
markdown block that lands in the create-proposal system prompt.

The registry replaces the hand-prose `_VALIDATION_REPAIR_EXAMPLES`
constant: structuring the data lets future consumers (e.g. validators
that want to share strings, prompt-mode renderers that want a different
section ordering) read the same source instead of the renderer copying
prose by hand.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ValidationRepairExample:
    """One bad-draft / validator-error / corrected-draft repair pair.

    Frozen + slotted: entries are canonical and must not mutate after
    construction, mirroring the discipline applied to `Pattern`.
    """

    bad_draft: str
    validation_error: str
    corrected_draft: str


VALIDATION_REPAIR_EXAMPLES_REGISTRY: tuple[ValidationRepairExample, ...] = (
    ValidationRepairExample(
        bad_draft="`{{ step_b.output.text }}` i `instructions`",
        validation_error=(
            "`variable references are not allowed in create_flow instructions`"
        ),
        corrected_draft=(
            "skriv bara vanliga instruktioner och låt backend kompilera underlaget"
        ),
    ),
    ValidationRepairExample(
        bad_draft='`output_type="text"` tillsammans med `output_fields`',
        validation_error="`output_fields require output_type=json`",
        corrected_draft=('byt till `output_type="json"` eller ta bort `output_fields`'),
    ),
    ValidationRepairExample(
        bad_draft=(
            '`document_delivery_mode="template_fill"` tillsammans med '
            '`output_type="pdf"`'
        ),
        validation_error="`template_fill requires output_type=docx`",
        corrected_draft="använd genererad PDF eller byt dokumenttypen till DOCX",
    ),
)


_HEADER = "# Validation Repair Examples"
_SUBHEADER = "## Felaktigt utkast → valideringsfel → korrigerat utkast"


def render_validation_repair_examples() -> str:
    """Render the validation-repair section for the create-proposal prompt.

    Output order matches `VALIDATION_REPAIR_EXAMPLES_REGISTRY`. Each
    entry occupies three labelled lines (`Bad draft:`, `Validation
    error:`, `Corrected draft:`) so the planner can read the bilingual
    pairing — the Swedish sub-heading frames the structure; the English
    labels keep the entry shape uniform across registry growth.
    """
    lines: list[str] = [_HEADER, "", _SUBHEADER, ""]
    for index, example in enumerate(VALIDATION_REPAIR_EXAMPLES_REGISTRY):
        if index > 0:
            lines.append("")
        lines.append("- Bad draft:")
        lines.append(f"  {example.bad_draft}")
        lines.append("- Validation error:")
        lines.append(f"  {example.validation_error}")
        lines.append("- Corrected draft:")
        lines.append(f"  {example.corrected_draft}")
    return "\n".join(lines)


__all__ = [
    "VALIDATION_REPAIR_EXAMPLES_REGISTRY",
    "ValidationRepairExample",
    "render_validation_repair_examples",
]
