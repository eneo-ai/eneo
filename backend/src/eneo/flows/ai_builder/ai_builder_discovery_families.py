from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from eneo.flows.ai_builder.ai_builder_slot_vocabulary import DiscoveryFamily
from eneo.flows.ai_builder.question_catalog import QUESTION_CATALOG

_NON_SLOT_QUESTION_FAMILY: dict[str, DiscoveryFamily] = {
    # Cross-slot contradiction gate; never asked as a catalog slot question.
    "comparison_scope_conflict": "case_scope",
    # Cross-input architecture conflict; wider than the primary input slot.
    "flow_input_architecture": "input_shape",
}

_CATALOG_QUESTION_FAMILY: dict[str, DiscoveryFamily] = {
    template.id: template.family for template in QUESTION_CATALOG.values()
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
