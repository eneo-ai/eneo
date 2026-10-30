"""A dismissed suggestion: one a flow's editors chose to hide.

A dismissal belongs to the flow, not to the person who made it: every
editor of the flow sees the suggestion hidden. It names the suggestion by
its fingerprint, which changes whenever the suggestion's premise does, so a
dismissal hides exactly the finding it was made for and lapses by itself
when the draft changes what the finding was about. Nothing else reads
dismissals: they never block, change or apply anything, and a flow package
carries none.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from eneo.flows.domain.flow_suggestion_model import FlowSuggestion

# A suggestion's fingerprint: the hex sha256 ``suggestion_fingerprint`` writes.
SUGGESTION_FINGERPRINT_PATTERN = r"^[0-9a-f]{64}$"


@dataclass(frozen=True, slots=True)
class FlowSuggestionDismissal:
    """Who dismissed the suggestion ``fingerprint`` of a flow and when;
    ``dismissed_by`` is None once that user is deleted. ``code`` is the
    suggestion's code as it was dismissed."""

    fingerprint: str
    code: str
    dismissed_by: UUID | None
    dismissed_at: datetime


@dataclass(frozen=True, slots=True)
class SuggestionsWithDismissals:
    """A draft's suggestions split by its dismissals: those shown and those
    dismissed, each list in the order of the suggestions."""

    shown: tuple[FlowSuggestion, ...]
    dismissed: tuple[tuple[FlowSuggestion, FlowSuggestionDismissal], ...]


def split_dismissed(
    suggestions: Sequence[FlowSuggestion],
    dismissals: Mapping[str, FlowSuggestionDismissal],
) -> SuggestionsWithDismissals:
    """``suggestions`` split into those no dismissal names and those one
    does. A dismissal of a fingerprint the draft no longer has names
    nothing."""
    shown: list[FlowSuggestion] = []
    dismissed: list[tuple[FlowSuggestion, FlowSuggestionDismissal]] = []
    for suggestion in suggestions:
        dismissal = dismissals.get(suggestion.fingerprint)
        if dismissal is None:
            shown.append(suggestion)
        else:
            dismissed.append((suggestion, dismissal))
    return SuggestionsWithDismissals(shown=tuple(shown), dismissed=tuple(dismissed))


__all__ = [
    "SUGGESTION_FINGERPRINT_PATTERN",
    "FlowSuggestionDismissal",
    "SuggestionsWithDismissals",
    "split_dismissed",
]
