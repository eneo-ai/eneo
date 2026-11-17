"""Which figures of a period become findings: what an administrator should
look at, worded by its signal.

Findings are computed on every read from the period's figures and stored
nowhere. A finding needs both a minimum number of cases and a minimum share
of its base, so a small assistant is not flagged on two questions. The
thresholds below are provisional until they are checked against the figures
of a real installation.
"""

from __future__ import annotations

from typing import NamedTuple

from eneo.analysis.insight_scope import FindingKind
from eneo.analysis.insights_repo import (
    KnowledgeCitations,
    KnowledgeSourceRow,
    PeriodFigures,
    ToolUseRow,
)


class FindingThreshold(NamedTuple):
    """A finding needs at least ``min_cases`` cases that are at least
    ``min_share`` of its base."""

    min_cases: int
    min_share: float


# Provisional: set from reasoning, not yet checked against the figures of a
# real installation. Cases and base per kind:
# - knowledge_missed: answers that searched the knowledge without a usable
#   hit, of the answers that searched.
# - unanswered: answers that say they cannot answer, of all answers.
# - rephrasing: conversations where the person seems to ask again, of all
#   conversations.
# - knowledge_unused: the period's answers, of themselves: an attached source
#   counts as unused only once the target answered enough questions to have
#   cited it, and then any uncited source counts.
# - negative_ratings: bad ratings with a comment, of all ratings (answers and
#   conversations together).
# - tool_failures: failed calls of one tool, of that tool's calls.
FINDING_THRESHOLDS: dict[FindingKind, FindingThreshold] = {
    "knowledge_missed": FindingThreshold(min_cases=10, min_share=0.25),
    "unanswered": FindingThreshold(min_cases=5, min_share=0.10),
    "rephrasing": FindingThreshold(min_cases=5, min_share=0.05),
    "knowledge_unused": FindingThreshold(min_cases=20, min_share=0.0),
    "negative_ratings": FindingThreshold(min_cases=3, min_share=0.20),
    "tool_failures": FindingThreshold(min_cases=5, min_share=0.20),
}

# Order of findings with the same affected count.
_KIND_ORDER: tuple[FindingKind, ...] = (
    "knowledge_missed",
    "unanswered",
    "negative_ratings",
    "rephrasing",
    "tool_failures",
    "knowledge_unused",
)


class FindingInputs(NamedTuple):
    """The period's figures the rules read."""

    figures: PeriodFigures
    # Conversations of the period that look like rephrasing.
    rephrasing: int
    knowledge: KnowledgeCitations
    tools: list[ToolUseRow]


class Finding(NamedTuple):
    kind: FindingKind
    affected: int
    base: int
    # knowledge_unused: the sources no answer cited.
    sources: tuple[KnowledgeSourceRow, ...] = ()
    # tool_failures: the tool that fails.
    tool: ToolUseRow | None = None


def passes(kind: FindingKind, cases: int, base: int) -> bool:
    """Whether ``cases`` of ``base`` meet the kind's threshold."""
    threshold = FINDING_THRESHOLDS[kind]
    if cases < threshold.min_cases or base <= 0:
        return False
    return cases / base >= threshold.min_share


def find_findings(inputs: FindingInputs) -> list[Finding]:
    """The findings of a period, most affected first."""
    figures = inputs.figures
    answers = figures.questions.total
    found: list[Finding] = []

    knowledge = figures.knowledge
    if knowledge is not None and passes(
        "knowledge_missed", knowledge.missed, knowledge.searched
    ):
        found.append(Finding("knowledge_missed", knowledge.missed, knowledge.searched))
    if passes("unanswered", figures.unanswered, answers):
        found.append(Finding("unanswered", figures.unanswered, answers))
    conversations = figures.conversations.total
    if passes("rephrasing", inputs.rephrasing, conversations):
        found.append(Finding("rephrasing", inputs.rephrasing, conversations))

    unused = tuple(inputs.knowledge.unused)
    if unused and passes("knowledge_unused", answers, answers):
        attached = len(unused) + sum(
            1 for source in inputs.knowledge.cited if source.attached
        )
        found.append(Finding("knowledge_unused", len(unused), attached, unused))

    ratings = (
        figures.answers_positive
        + figures.answers_negative
        + figures.conversations_positive
        + figures.conversations_negative
    )
    commented_bad = (
        figures.answers_negative_with_comment
        + figures.conversations_negative_with_comment
    )
    if passes("negative_ratings", commented_bad, ratings):
        found.append(Finding("negative_ratings", commented_bad, ratings))

    for tool in inputs.tools:
        if passes("tool_failures", tool.failed, tool.calls):
            found.append(Finding("tool_failures", tool.failed, tool.calls, tool=tool))

    return sorted(
        found,
        key=lambda finding: (-finding.affected, _KIND_ORDER.index(finding.kind)),
    )
