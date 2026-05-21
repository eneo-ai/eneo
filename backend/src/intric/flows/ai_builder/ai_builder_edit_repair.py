"""Constrained repair logic for AI Builder edit-mode description updates.

When a semantic change (e.g., audio → document) is detected but the LLM didn't
provide an updated description, this module decides whether to attempt a
description-only repair and validates that the repair didn't change anything else.
"""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_description_semantics import (
    DescriptionProvenance,
    description_hash,
)
from intric.flows.ai_builder.ai_builder_edit_models import EditAdvisory
from intric.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
)


def should_attempt_description_repair(
    *,
    advisories: list[EditAdvisory],
    current_description: str | None,
    current_provenance: DescriptionProvenance | None,
) -> bool:
    """Decide whether to attempt a constrained description repair.

    Returns True only when:
    1. There's a flow_description_update_required advisory
    2. Provenance is builder_managed (not manually edited)
    3. Current description hash matches the last generated hash (no manual edits)
    """
    if not any(a.code == "flow_description_update_required" for a in advisories):
        return False

    if current_provenance is None:
        return False

    if current_provenance.mode != "builder_managed":
        return False

    if current_provenance.last_generated_hash is None:
        return False

    current_hash = description_hash(current_description)
    return current_hash == current_provenance.last_generated_hash


def validate_repair_invariance(
    original_spec: FlowDraftSpecCore,
    repaired_spec: FlowDraftSpecCore,
) -> bool:
    """Verify that a repair only changed the description, nothing else.

    Compares spec_hash with zeroed descriptions to ensure structural invariance.
    """
    zeroed_original = original_spec.model_copy(update={"flow_description": ""})
    zeroed_repaired = repaired_spec.model_copy(update={"flow_description": ""})
    return zeroed_original.spec_hash() == zeroed_repaired.spec_hash()
