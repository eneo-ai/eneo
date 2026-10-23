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


def test_pdf_upload_refusal_taxonomy():
    code = FlowApiErrorCode("flow_run_upload_pdf_exceeds_limit")
    entry = FLOW_ERROR_TAXONOMY[code]

    assert entry.category == "Run input"
    assert entry.handling_phase == "Request path"
    assert "split" in entry.consumer_action.lower()
    assert "administrator" in entry.consumer_action.lower()


def test_unfinished_checks_and_unreadable_values_are_not_blamed_on_the_wrong_party() -> (
    None
):
    # An unfinished tool-argument check is typed_io_contract_not_checked, so
    # the schema code no longer claims "could not be checked"; copy_input
    # reports typed_io_output_parse_failed with no model run, so its cause
    # names a step's output value as well as the model's output.
    not_checked = FLOW_ERROR_TAXONOMY[FlowApiErrorCode.TYPED_IO_CONTRACT_NOT_CHECKED]
    schema = FLOW_ERROR_TAXONOMY[FlowApiErrorCode.TYPED_IO_TOOL_INVALID_SCHEMA]
    parse = FLOW_ERROR_TAXONOMY[FlowApiErrorCode.TYPED_IO_OUTPUT_PARSE_FAILED]

    assert "tool call" in not_checked.cause
    assert "could not be checked" not in schema.cause
    assert "step's output value" in parse.cause
    assert "nested too deep" in parse.cause
