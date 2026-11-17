"""The finding rules: a finding needs both enough cases and a large enough
share of its base, and the findings come most affected first."""

from typing import Any
from uuid import uuid4

from eneo.analysis.insight_findings import (
    FINDING_THRESHOLDS,
    FindingInputs,
    find_findings,
    passes,
)
from eneo.analysis.insights_repo import (
    KnowledgeCitations,
    KnowledgeSourceRow,
    KnowledgeUse,
    PeriodFigures,
    SourceCounts,
    ToolUseRow,
)


def _figures(answers: int, **overrides: Any) -> PeriodFigures:
    fields: dict[str, Any] = {name: 0 for name in PeriodFigures._fields}
    counts = SourceCounts(answers, answers, 0, 0)
    fields.update(conversations=counts, questions=counts, knowledge=None)
    fields.update(overrides)
    return PeriodFigures(**fields)


def _source(name: str, *, answers: int = 0) -> KnowledgeSourceRow:
    return KnowledgeSourceRow("collection", uuid4(), name, answers, True)


NO_KNOWLEDGE = KnowledgeCitations(0, 0, [], [])


def test_a_finding_needs_both_its_cases_and_its_share():
    threshold = FINDING_THRESHOLDS["unanswered"]

    # Two of four answers: a large share, too few cases.
    assert not passes("unanswered", 2, 4)
    # Enough cases, too small a share of a large assistant.
    assert not passes("unanswered", threshold.min_cases, 1000)
    assert passes("unanswered", threshold.min_cases, threshold.min_cases)
    assert not passes("unanswered", threshold.min_cases, 0)


def test_findings_come_most_affected_first_and_only_past_their_thresholds():
    inputs = FindingInputs(
        figures=_figures(
            100,
            unanswered=12,
            knowledge=KnowledgeUse(searched=80, missed=30),
            # 3 bad commented ratings of 5: a finding.
            answers_positive=2,
            answers_negative=3,
            answers_negative_with_comment=3,
        ),
        # 2 conversations of 100: too few.
        rephrasing=2,
        knowledge=KnowledgeCitations(
            100, 60, [_source("Bygglov", answers=60)], [_source("Gammalt")]
        ),
        tools=[
            ToolUseRow(None, "Grounding", "get_chat_grounding", None, 10, 6, 0),
            # Many calls, a small share failed.
            ToolUseRow("web_search", None, None, None, 200, 9, 0),
        ],
    )

    findings = find_findings(inputs)

    assert [(f.kind, f.affected, f.base) for f in findings] == [
        ("knowledge_missed", 30, 80),
        ("unanswered", 12, 100),
        ("tool_failures", 6, 10),
        ("negative_ratings", 3, 5),
        ("knowledge_unused", 1, 2),
    ]
    tool = next(f.tool for f in findings if f.kind == "tool_failures")
    assert tool is not None and tool.server_name == "Grounding"
    unused = next(f for f in findings if f.kind == "knowledge_unused")
    assert [source.name for source in unused.sources] == ["Gammalt"]


def test_uncited_knowledge_waits_for_enough_answers():
    citations = KnowledgeCitations(5, 0, [], [_source("Bygglov")])
    few = find_findings(FindingInputs(_figures(5), 0, citations, []))
    enough = find_findings(
        FindingInputs(
            _figures(FINDING_THRESHOLDS["knowledge_unused"].min_cases), 0, citations, []
        )
    )

    assert few == []
    assert [f.kind for f in enough] == ["knowledge_unused"]
    assert find_findings(FindingInputs(_figures(500), 0, NO_KNOWLEDGE, [])) == []
