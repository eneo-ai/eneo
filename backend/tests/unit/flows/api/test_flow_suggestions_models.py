"""The suggestions answer with the flow's dismissals: dismissed suggestions
left out and counted, or listed in their place and marked."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from eneo.flows.api.flow_suggestions_models import FlowSuggestionsPublic
from eneo.flows.domain.flow_suggestion_dismissal import FlowSuggestionDismissal
from eneo.flows.domain.flow_suggestions import (
    FlowSuggestion,
    FlowSuggestionCode,
    FlowSuggestionFix,
    FlowSuggestionImpact,
)

_FLOW = UUID(int=1)
_USER = UUID(int=2)
_AT = datetime(2026, 10, 25, 9, 30, tzinfo=timezone.utc)


def _suggestion(fingerprint: str) -> FlowSuggestion:
    return FlowSuggestion(
        code=FlowSuggestionCode.UNREAD_RESULT,
        fingerprint=fingerprint,
        steps=(UUID(int=10),),
        message="Nobody reads step 1.",
        impact=FlowSuggestionImpact(basis="definition", level="medium"),
        fix=FlowSuggestionFix(kind="advice"),
    )


def _dismissal(fingerprint: str) -> FlowSuggestionDismissal:
    return FlowSuggestionDismissal(
        fingerprint=fingerprint,
        code=FlowSuggestionCode.UNREAD_RESULT.value,
        dismissed_by=_USER,
        dismissed_at=_AT,
    )


_SUGGESTIONS = (_suggestion("a" * 64), _suggestion("b" * 64), _suggestion("c" * 64))
# One of the draft's suggestions, and one the draft no longer has.
_DISMISSALS = {
    "b" * 64: _dismissal("b" * 64),
    "d" * 64: _dismissal("d" * 64),
}


def _answer(*, include_dismissed: bool) -> FlowSuggestionsPublic:
    return FlowSuggestionsPublic.from_suggestions(
        flow_id=_FLOW,
        draft_revision=4,
        suggestions=_SUGGESTIONS,
        dismissals=_DISMISSALS,
        include_dismissed=include_dismissed,
    )


def test_a_dismissed_suggestion_is_left_out_and_counted() -> None:
    answer = _answer(include_dismissed=False)

    assert [item.fingerprint for item in answer.items] == ["a" * 64, "c" * 64]
    assert all(item.dismissed is None for item in answer.items)
    # A dismissal of a fingerprint the draft no longer has hides nothing.
    assert answer.dismissed_count == 1


def test_include_dismissed_lists_it_in_its_place_with_who_and_when() -> None:
    answer = _answer(include_dismissed=True)

    assert [item.fingerprint for item in answer.items] == [
        "a" * 64,
        "b" * 64,
        "c" * 64,
    ]
    dismissed = answer.items[1].dismissed
    assert dismissed is not None
    assert (dismissed.dismissed_by, dismissed.dismissed_at) == (_USER, _AT)
    assert answer.items[0].dismissed is None
    assert answer.dismissed_count == 1


def test_an_answer_without_dismissals_counts_none() -> None:
    answer = FlowSuggestionsPublic.from_suggestions(
        flow_id=_FLOW, draft_revision=4, suggestions=_SUGGESTIONS
    )

    assert len(answer.items) == 3
    assert answer.dismissed_count == 0
