"""A reviewer's rejection reason is trimmed, required and bounded."""

from __future__ import annotations

import pytest

from eneo.flows.domain.review_reject_reason import (
    FLOW_REVIEW_REJECT_REASON_MAX_LENGTH,
    normalize_review_reject_reason,
)
from eneo.flows.flow_api_exceptions import FlowBadRequestException


def test_the_reason_is_trimmed():
    assert normalize_review_reject_reason("  Wrong case number. \n") == (
        "Wrong case number."
    )


@pytest.mark.parametrize("reason", ["", "   ", "\n\t"])
def test_a_blank_reason_is_refused(reason: str):
    with pytest.raises(FlowBadRequestException) as exc_info:
        normalize_review_reject_reason(reason)

    assert exc_info.value.code == "flow_review_reject_reason_required"


def test_the_limit_counts_the_trimmed_reason():
    at_limit = "å" * FLOW_REVIEW_REJECT_REASON_MAX_LENGTH

    assert normalize_review_reject_reason(f"  {at_limit}  ") == at_limit


def test_a_reason_over_the_limit_is_refused_with_the_limit():
    with pytest.raises(FlowBadRequestException) as exc_info:
        normalize_review_reject_reason("x" * (FLOW_REVIEW_REJECT_REASON_MAX_LENGTH + 1))

    assert exc_info.value.code == "flow_review_reject_reason_too_long"
    assert exc_info.value.context == {"max_length": 1024}
