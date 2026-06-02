from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from intric.flows.ai_builder.ai_builder_slot_vocabulary import DiscoveryFamily
from intric.flows.ai_builder.question_catalog import (
    QUESTION_CATALOG,
    legacy_question_id_for_slot,
)

_NON_SLOT_QUESTION_FAMILY: dict[str, DiscoveryFamily] = {
    # Cross-slot contradiction gate; never asked as a catalog slot question.
    "comparison_scope_conflict": "case_scope",
    # Legacy processing-scope question; not a named architectural slot today.
    "case_scope": "case_scope",
    # Reference-source comparison gate; no single slot owns it yet.
    "comparison_scope": "case_scope",
    # Cross-input architecture conflict; wider than the primary input slot.
    "flow_input_architecture": "input_shape",
    # Source-document kind refinement; currently lives in discovery rules.
    "document_kind": "input_shape",
    # PDF style refinement after terminal output is already known.
    "final_pdf_type": "output_style",
    # Reader/audience style refinement, not an output artifact slot.
    "output_reader": "output_style",
    # Output-scope style refinement, not a terminal artifact choice.
    "final_output_scope": "output_style",
}

_CATALOG_QUESTION_FAMILY: dict[str, DiscoveryFamily] = {
    legacy_question_id_for_slot(template.id): template.family
    for template in QUESTION_CATALOG.values()
}

QUESTION_FAMILY: Mapping[str, DiscoveryFamily] = MappingProxyType(
    {
        **_NON_SLOT_QUESTION_FAMILY,
        **_CATALOG_QUESTION_FAMILY,
    }
)

ALL_DISCOVERY_FAMILIES: frozenset[DiscoveryFamily] = frozenset(QUESTION_FAMILY.values())


def family_for_issue(
    issue_id: str, *, default: DiscoveryFamily | None = None
) -> DiscoveryFamily | None:
    family = QUESTION_FAMILY.get(issue_id)
    if family is not None:
        return family
    return default
