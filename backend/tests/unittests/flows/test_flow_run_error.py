from __future__ import annotations

from typing import get_type_hints
from uuid import uuid4

import pytest
from pydantic import ValidationError

from intric.flows.enums import FlowRunLifecycleSource
from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.flows.flow_run_error import (
    FlowRunError,
    FlowRunErrorDetails,
    dump_flow_run_error,
    parse_flow_run_error,
)


def test_flow_run_error_from_source_requires_public_error_code() -> None:
    assert get_type_hints(FlowRunError.from_source)["code"] is FlowApiErrorCode


def test_flow_run_error_from_source_preserves_machine_code_and_step_context() -> None:
    step_id = uuid4()

    error = FlowRunError.from_source(
        FlowRunLifecycleSource.INVALID_FLOW_DEFINITION,
        code=FlowApiErrorCode.REVIEW_POLICY_INVALID,
        message="Step 3 (Analysera bakgrund): review_policy is invalid.",
        step_id=step_id,
        step_order=3,
        details=FlowRunErrorDetails(step_description="Analysera bakgrund"),
    )

    assert error == FlowRunError(
        code="flow_review_policy_invalid",
        message="Step 3 (Analysera bakgrund): review_policy is invalid.",
        source=FlowRunLifecycleSource.INVALID_FLOW_DEFINITION,
        step_id=step_id,
        step_order=3,
        details={"step_description": "Analysera bakgrund"},
    )


def test_dump_flow_run_error_returns_openapi_safe_json_object() -> None:
    step_id = uuid4()
    error = FlowRunError.from_source(
        FlowRunLifecycleSource.EXECUTOR_FAILED,
        code=FlowApiErrorCode.TYPED_IO_OUTPUT_PARSE_FAILED,
        message="Step output was not valid JSON.",
        step_id=step_id,
        step_order=4,
    )

    assert dump_flow_run_error(error) == {
        "schema_version": 1,
        "code": "typed_io_output_parse_failed",
        "message": "Step output was not valid JSON.",
        "source": "executor_failed",
        "step_id": str(step_id),
        "step_order": 4,
    }


def test_flow_run_error_details_keep_only_public_step_context() -> None:
    details = FlowRunErrorDetails.from_bad_request_context(
        {
            "step_description": "Analysera bakgrund",
            "secret_token": "must not leak",
        }
    )

    assert details == FlowRunErrorDetails(step_description="Analysera bakgrund")
    assert details.model_dump(exclude_none=True) == {
        "step_description": "Analysera bakgrund"
    }


def test_flow_run_error_details_truncate_step_description_budget() -> None:
    details = FlowRunErrorDetails.from_bad_request_context(
        {"step_description": "x" * 300}
    )

    assert details is not None
    assert details.step_description == "x" * 256


def test_flow_run_error_details_reject_unknown_public_keys() -> None:
    with pytest.raises(ValidationError):
        FlowRunErrorDetails.model_validate({"secret_token": "must not leak"})


def test_parse_flow_run_error_rejects_unstructured_legacy_values() -> None:
    with pytest.raises(ValidationError):
        parse_flow_run_error("Step review_policy is invalid.")


def test_parse_flow_run_error_accepts_historical_string_codes() -> None:
    error = parse_flow_run_error(
        {
            "schema_version": 1,
            "code": "legacy_uncataloged_code",
            "message": "Stored before the public taxonomy was closed.",
            "source": "executor_failed",
        }
    )

    assert error is not None
    assert error.code == "legacy_uncataloged_code"


def test_flow_run_error_requires_machine_readable_code() -> None:
    with pytest.raises(ValidationError):
        FlowRunError(
            code="Invalid Code With Spaces",
            message="Invalid error code.",
            source=FlowRunLifecycleSource.INVALID_FLOW_DEFINITION,
        )


def test_flow_run_error_from_source_truncates_unbounded_messages() -> None:
    error = FlowRunError.from_source(
        FlowRunLifecycleSource.EXECUTOR_FAILED,
        code=FlowApiErrorCode.RUN_TASK_FAILURE,
        message="x" * 5000,
    )

    assert len(error.message) == 4096
    assert error.message.endswith("... [truncated]")
