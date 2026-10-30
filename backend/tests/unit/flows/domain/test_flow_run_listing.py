from __future__ import annotations

import pytest

from eneo.flows.domain.flow_run_listing import FlowRunListing


def test_a_search_is_trimmed_and_composed_as_labels_are_stored() -> None:
    decomposed = "Café 7"

    listing = FlowRunListing.of(search=f"  {decomposed} ")

    assert listing.search == "Café 7"


@pytest.mark.parametrize("search", [None, "", "   "])
def test_a_blank_search_searches_nothing(search: str | None) -> None:
    assert FlowRunListing.of(search=search).search is None


def test_the_default_listing_is_newest_created_first() -> None:
    assert FlowRunListing.of() == FlowRunListing(
        search=None, sort="created_at", order="desc"
    )
