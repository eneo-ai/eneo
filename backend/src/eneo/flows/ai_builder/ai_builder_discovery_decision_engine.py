"""Which discovery issues become this turn's questions.

The slot interaction policy decides, for every requirement slot, whether it is
asked, assumed, accepted or committed; this module maps that decision onto the
issues discovery built. Non-slot gates (a comparison contradiction, a mixed
input architecture, an unsupported delivery) are asked whenever discovery
raised them. Edit mode suppresses families the edit does not touch. What comes
out is the ask list, in policy order.

Before this module read the policy, the same decision was spread over a
question budget keyed on phrases in the brief, a one-question-per-family gate,
per-issue "assumption safe" predicates and heuristics, and separate impact and
priority maps. They disagreed, and which one won depended on evaluation order.
"""

from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_discovery_families import family_for_issue
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import question_category
from eneo.flows.ai_builder.ai_builder_discovery_models import (
    DiscoveryIssue,
    DiscoveryProfile,
)
from eneo.flows.ai_builder.ai_builder_discovery_priority import (
    sort_discovery_issues,
)
from eneo.flows.ai_builder.ai_builder_discovery_questions import (
    question_exposure_for_id,
    question_suggestion_for_id,
)
from eneo.flows.ai_builder.ai_builder_slot_interaction_policy import (
    SLOT_INTERACTION_POLICIES,
    evaluate_slot_interaction,
    slot_interaction_order,
)


def apply_discovery_decision_engine(
    *,
    issues: list[DiscoveryIssue],
    profile: DiscoveryProfile,
    slot_questions_allowed: bool,
) -> tuple[list[DiscoveryIssue], list[str]]:
    """Select this turn's questions from the issues discovery raised.

    Returns the selected issues, ordered, and the question ids among them.
    Slot questions wait until discovery has something to work with
    (`slot_questions_allowed`); before that the model runs free discovery and
    only the gates discovery raised are kept.
    """

    slot_issues: dict[str, DiscoveryIssue] = {}
    selected: list[DiscoveryIssue] = []
    for issue in issues:
        question_id = _question_id(issue)
        if (
            question_id is not None
            and question_exposure_for_id(question_id) != "user_requirement"
        ):
            continue
        if _family_suppressed(issue.issue_id, question_id, profile):
            continue
        slot_name = _policy_slot_for(issue.issue_id)
        if slot_name is None:
            # A gate discovery raised is asked as raised: its condition is the
            # builder's, not a slot's.
            selected.append(issue)
            continue
        slot_issues.setdefault(slot_name, issue)

    state = profile.planning_state
    slot_names = (
        sorted(SLOT_INTERACTION_POLICIES, key=slot_interaction_order)
        if slot_questions_allowed
        else ()
    )
    for slot_name in slot_names:
        policy = SLOT_INTERACTION_POLICIES[slot_name]
        if (
            evaluate_slot_interaction(policy, state, freeform_text=profile.text)
            != "ask"
        ):
            continue
        if _family_suppressed(slot_name, slot_name, profile):
            continue
        issue = slot_issues.get(slot_name) or _issue_for_slot(slot_name, profile)
        if issue is not None:
            selected.append(issue)

    ordered = sort_discovery_issues(selected)
    return ordered, [
        question_id
        for issue in ordered
        if (question_id := _question_id(issue)) is not None
    ]


def _question_id(issue: DiscoveryIssue) -> str | None:
    return issue.suggestion.question_id if issue.suggestion is not None else None


def _policy_slot_for(issue_id: str) -> str | None:
    """The slot an issue stands for, by its own id.

    A gate may reuse a slot's question (the comparison contradiction asks the
    comparison question; the low-confidence gate re-asks the slot it doubts),
    but it is raised on its own condition, so only an issue named after a slot
    is the slot's.
    """

    return issue_id if issue_id in SLOT_INTERACTION_POLICIES else None


def _family_suppressed(
    issue_id: str, question_id: str | None, profile: DiscoveryProfile
) -> bool:
    if not profile.edit_mode:
        return False
    family = family_for_issue(issue_id) or family_for_issue(question_id or "")
    return family is not None and family not in profile.edit_scope.active_families


def _issue_for_slot(slot_name: str, profile: DiscoveryProfile) -> DiscoveryIssue | None:
    """The question for a slot the policy asks about without a raised issue.

    The catalog owns the wording; discovery's own builders only add a more
    specific message when their text rules fired.
    """

    suggestion = question_suggestion_for_id(slot_name, language=profile.language)
    if suggestion is None:
        return None
    return DiscoveryIssue(
        issue_id=slot_name,
        category=question_category(slot_name),
        severity="blocking",
        message=suggestion.question,
        suggestion=suggestion,
        question_level="blocking",
    )


__all__ = ["apply_discovery_decision_engine"]
