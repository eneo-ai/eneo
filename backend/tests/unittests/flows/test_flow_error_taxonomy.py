from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_error_taxonomy import (
    FLOW_ERROR_TAXONOMY,
    validate_flow_error_taxonomy,
)


def test_evidence_export_too_large_describes_whole_bundle_limits() -> None:
    validate_flow_error_taxonomy()
    entry = FLOW_ERROR_TAXONOMY[FlowApiErrorCode.EVIDENCE_EXPORT_TOO_LARGE]

    assert "row" in entry.cause
    assert "logical-byte" in entry.cause
    assert "section and limit context fields" in entry.consumer_action
    assert "run view" in entry.user_action


def test_republish_refusal_taxonomy() -> None:
    entry = FLOW_ERROR_TAXONOMY[
        FlowApiErrorCode("flow_assistant_snapshot_republish_required")
    ]
    assert entry.category == "Published definition"
    assert entry.handling_phase == "Request path or run execution"
    assert "republish" in entry.consumer_action.lower()
