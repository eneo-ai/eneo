"""The review reject request states its reason limit and refuses with the
review service's own codes."""

from __future__ import annotations

import pytest

from eneo.flows.api.flow_models import FlowRunReviewCheckpointRejectRequest
from eneo.flows.flow_api_exceptions import FlowBadRequestException


def test_the_reject_request_documents_the_reason_bounds():
    schema = FlowRunReviewCheckpointRejectRequest.model_json_schema()

    reason = schema["properties"]["reason"]
    assert reason["minLength"] == 1
    assert reason["maxLength"] == 1024


def test_the_reject_request_trims_the_reason():
    request = FlowRunReviewCheckpointRejectRequest.model_validate(
        {"expected_checkpoint_revision": 1, "reason": "  Wrong case.  "}
    )

    assert request.reason == "Wrong case."


@pytest.mark.parametrize(
    ("reason", "code"),
    [
        ("   ", "flow_review_reject_reason_required"),
        ("x" * 1025, "flow_review_reject_reason_too_long"),
    ],
)
def test_the_reject_request_refuses_with_the_review_codes(reason: str, code: str):
    with pytest.raises(FlowBadRequestException) as exc_info:
        FlowRunReviewCheckpointRejectRequest.model_validate(
            {"expected_checkpoint_revision": 1, "reason": reason}
        )

    assert exc_info.value.code == code
