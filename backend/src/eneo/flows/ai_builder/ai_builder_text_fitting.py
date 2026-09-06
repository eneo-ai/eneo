"""Fit several texts into one bounded prompt without inventing quotas.

Attachment excerpts and review-run excerpts share the same problem: a few
texts of unequal length, and one predicate that says whether a rendering
fits the request budget of the model actually chosen. The allocation is
global and fair (max-min over the texts that still have characters to
give), and the largest fair budget that fits is found on the rendered
result by doubling, then bisecting, so the number that decides is always
the measured payload and never a character or token guess.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping, Sequence
from typing import TypeVar

K = TypeVar("K", bound=Hashable)
T = TypeVar("T")


def fair_text_allocations(
    items: Sequence[tuple[K, str]],
    char_budget: int,
) -> dict[K, int]:
    """Characters per item for one budget: equal shares, remainders re-shared.

    An item shorter than its share gives the rest back, so the budget goes
    where there is text to read; a long text is cut only when the others
    have been served their fair share.
    """

    allocations = {key: 0 for key, _ in items}
    remaining = min(char_budget, sum(len(text) for _, text in items))
    while remaining > 0:
        active = [(key, text) for key, text in items if allocations[key] < len(text)]
        if not active:
            break
        fair_share = max(1, remaining // len(active))
        for key, text in active:
            allocation = min(fair_share, len(text) - allocations[key], remaining)
            allocations[key] += allocation
            remaining -= allocation
            if remaining == 0:
                break
    return allocations


def fit_text_allocations(
    items: Sequence[tuple[K, str]],
    *,
    render: Callable[[Mapping[K, int]], T],
    fits: Callable[[T], bool],
) -> T:
    """The rendering with the largest fair character budget that fits.

    ``render`` builds the candidate for one allocation; ``fits`` measures it
    the way the request will be measured. When nothing fits, the rendering
    with no text is returned so the caller can say what it left out.
    """

    total_available_chars = sum(len(text) for _, text in items)
    empty = render({})
    if total_available_chars == 0 or not fits(empty):
        return empty

    def render_budget(char_budget: int) -> T:
        bounded = min(max(char_budget, 0), total_available_chars)
        return render(fair_text_allocations(items, bounded))

    lower = 0
    upper = 1
    while upper < total_available_chars and fits(render_budget(upper)):
        lower = upper
        upper = min(total_available_chars, upper * 2)
    if fits(render_budget(upper)):
        return render_budget(upper)
    while lower + 1 < upper:
        midpoint = (lower + upper) // 2
        if fits(render_budget(midpoint)):
            lower = midpoint
        else:
            upper = midpoint
    return render_budget(lower)
