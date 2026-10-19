from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from eneo.flows.ai_builder.ai_builder_result_contract import ResultObligation
from eneo.flows.ai_builder.ai_builder_slot_classification_contract import (
    UNKNOWN_SLOT_VALUE,
    AbsentSlotClassificationOutcome,
    ClassifiedCheckpointUpdate,
    ClassifiedEvidence,
    ClassifiedFileRole,
    ClassifiedFormIntake,
    ClassifiedNamedResultDelta,
    ClassifiedSchemaDirection,
    ExplicitlyUncertainSlotClassificationOutcome,
    ResolvedSlotClassificationOutcome,
    SlotClassificationConfidence,
    SlotClassificationDiagnostic,
    SlotClassificationEvidenceLevel,
    SlotClassificationOutcome,
    SlotClassificationResult,
)
from eneo.flows.ai_builder.planning_state import ExampleOutputConstraintEvidence


@dataclass(frozen=True, slots=True)
class ClassifiedSlot:
    """One slot as a test states it; `slot_classification_result` maps it to
    the typed outcome the production contract carries."""

    slot_name: str
    value: str
    confidence: SlotClassificationConfidence
    reason: str
    evidence: tuple[ClassifiedEvidence, ...] = ()
    evidence_level: SlotClassificationEvidenceLevel = "inferred"
    classification_kind: Literal["resolved", "explicitly_uncertain"] = "resolved"


def resolved_outcome(slot: ClassifiedSlot) -> ResolvedSlotClassificationOutcome:
    return ResolvedSlotClassificationOutcome(
        value=slot.value,
        confidence=slot.confidence,
        reason=slot.reason,
        evidence=slot.evidence,
        evidence_level=slot.evidence_level,
    )


def slot_classification_result(
    *,
    slots: tuple[ClassifiedSlot, ...] = (),
    slot_outcomes: Mapping[str, SlotClassificationOutcome] | None = None,
    diagnostics: tuple[SlotClassificationDiagnostic, ...] = (),
    file_roles: tuple[ClassifiedFileRole, ...] = (),
    checkpoint_updates: tuple[ClassifiedCheckpointUpdate, ...] = (),
    form_intake: ClassifiedFormIntake | None = None,
    named_result_evidence: ClassifiedNamedResultDelta | None = None,
    example_output_constraints: ExampleOutputConstraintEvidence | None = None,
    schema_direction: ClassifiedSchemaDirection | None = None,
    secondary_obligations: tuple[ResultObligation, ...] = (),
    cached: bool = False,
) -> SlotClassificationResult:
    outcomes = (
        dict(slot_outcomes)
        if slot_outcomes is not None
        else {
            slot.slot_name: (
                ExplicitlyUncertainSlotClassificationOutcome(quote=slot.evidence[0])
                if slot.classification_kind == "explicitly_uncertain"
                and len(slot.evidence) == 1
                else (
                    AbsentSlotClassificationOutcome()
                    if slot.value == UNKNOWN_SLOT_VALUE
                    else resolved_outcome(slot)
                )
            )
            for slot in slots
        }
    )
    return SlotClassificationResult(
        slot_outcomes=outcomes,
        diagnostics=diagnostics,
        file_roles=file_roles,
        checkpoint_updates=checkpoint_updates,
        form_intake=form_intake,
        named_result_evidence=named_result_evidence,
        example_output_constraints=example_output_constraints,
        schema_direction=schema_direction,
        secondary_obligations=secondary_obligations,
        cached=cached,
    )
