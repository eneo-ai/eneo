from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from eneo.flows.ai_builder.ai_builder_discovery_models import DiscoveryIssue
from eneo.flows.ai_builder.question_catalog import QUESTION_CATALOG

_NON_SLOT_DISCOVERY_ISSUE_PRIORITY: dict[str, int] = {
    # Cross-slot contradiction gate; must precede ordinary clarification.
    "comparison_scope_conflict": 0,
    # Legacy processing-scope question; not a named architectural slot today.
    "case_scope": 10,
    # Unsupported outbound delivery is a capability blocker; surface that
    # before asking unrelated input/output refinement questions.
    "external_delivery_unsupported": 15,
    # Cross-input architecture conflict; wider than the primary input slot.
    "flow_input_architecture": 25,
    # Source-document kind refinement; currently lives in discovery rules.
    "document_kind": 40,
    # Reference-source comparison gate; no single slot owns it yet.
    "comparison_scope": 60,
    # PDF style refinement after terminal output is already known.
    "final_pdf_type": 75,
    # Reader/audience style refinement, not an output artifact slot.
    "output_reader": 80,
    # Output-scope style refinement, not a terminal artifact choice.
    "final_output_scope": 90,
}

_CATALOG_DISCOVERY_ISSUE_PRIORITY: dict[str, int] = {
    template.id: template.priority_base for template in QUESTION_CATALOG.values()
}

DISCOVERY_ISSUE_PRIORITY: Mapping[str, int] = MappingProxyType(
    {
        **_NON_SLOT_DISCOVERY_ISSUE_PRIORITY,
        **_CATALOG_DISCOVERY_ISSUE_PRIORITY,
    }
)


def sort_discovery_issues(issues: list[DiscoveryIssue]) -> list[DiscoveryIssue]:
    return sorted(
        issues,
        key=lambda issue: (
            0 if issue.severity == "blocking" else 1,
            DISCOVERY_ISSUE_PRIORITY.get(issue.issue_id, 999),
        ),
    )
