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
