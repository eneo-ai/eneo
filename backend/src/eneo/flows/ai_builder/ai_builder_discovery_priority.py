from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_discovery_models import DiscoveryIssue
from eneo.flows.ai_builder.ai_builder_slot_interaction_policy import (
    slot_interaction_order,
)

# Gates that are not requirement slots place themselves. Slot questions take
# their order from the interaction policy table.
_NON_SLOT_DISCOVERY_ISSUE_PRIORITY: dict[str, int] = {
    # Cross-slot contradiction gate; must precede ordinary clarification.
    "comparison_scope_conflict": 0,
    # Unsupported outbound delivery is a capability blocker; surface that
    # before asking unrelated input/output refinement questions.
    "external_delivery_unsupported": 1,
    # Cross-input architecture conflict; wider than the primary input slot.
    "flow_input_architecture": 2,
}


def discovery_issue_priority(issue_id: str) -> int:
    """Return the canonical ordering priority for one discovery issue."""

    priority = _NON_SLOT_DISCOVERY_ISSUE_PRIORITY.get(issue_id)
    if priority is not None:
        return priority
    return slot_interaction_order(issue_id)


def sort_discovery_issues(issues: list[DiscoveryIssue]) -> list[DiscoveryIssue]:
    return sorted(
        issues,
        key=lambda issue: (
            0 if issue.severity == "blocking" else 1,
            discovery_issue_priority(
                issue.issue_id
                if issue.issue_id in _NON_SLOT_DISCOVERY_ISSUE_PRIORITY
                or issue.suggestion is None
                else issue.suggestion.question_id
            ),
        ),
    )
