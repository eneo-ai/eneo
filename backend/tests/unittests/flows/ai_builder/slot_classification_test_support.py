from __future__ import annotations

from collections.abc import Mapping

from eneo.flows.ai_builder.ai_builder_result_contract import ResultObligation
from eneo.flows.ai_builder.ai_builder_slot_classification_contract import (
    UNKNOWN_SLOT_VALUE,
    AbsentSlotClassificationOutcome,
    ClassifiedCheckpointUpdate,
    ClassifiedFileRole,
    ClassifiedFormIntake,
    ClassifiedNamedResultDelta,
    ClassifiedSchemaDirection,
    ClassifiedSlot,
    ExplicitlyUncertainSlotClassificationOutcome,
    ResolvedSlotClassificationOutcome,
    SlotClassificationDiagnostic,
    SlotClassificationOutcome,
    SlotClassificationResult,
)
from eneo.flows.ai_builder.planning_state import ExampleOutputConstraintEvidence


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
                    else ResolvedSlotClassificationOutcome.from_classified_slot(slot)
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
