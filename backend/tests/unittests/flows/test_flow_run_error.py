from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import get_type_hints
from uuid import uuid4

import pytest
from pydantic import ValidationError

from intric.authentication.principal_types import PrincipalType
from intric.flows.domain.flow import FlowRun, FlowRunStatus
from intric.flows.enums import FlowRunLifecycleSource
from intric.flows.flow_api_error_code import (
    FLOW_RUN_TERMINAL_ERROR_CODES,
    FlowApiErrorCode,
)
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
        code=FlowApiErrorCode.REVIEW_POLICY_INVALID,
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


def _assert_corrupt_run_error(error: FlowRunError | None) -> None:
    assert error == FlowRunError(
        code=FlowApiErrorCode.RUN_ERROR_PAYLOAD_INVALID,
        message="Persisted flow run error payload is invalid.",
    )


@pytest.mark.parametrize(
    "payload,leaked_text",
    [
        ("Step review_policy is invalid.", "review_policy"),
        ({"schema_version": 1, "code": "flow_task_failure"}, "flow_task_failure"),
        (
            {
                "schema_version": 2,
                "code": "flow_task_failure",
                "message": "Unsupported schema with secret-token.",
            },
            "secret-token",
        ),
        (
            {
                "schema_version": 1,
                "code": "flow_task_failure",
                "message": "Invalid source with secret-token.",
                "source": "not-a-source",
            },
            "secret-token",
        ),
        (
            {
                "schema_version": 1,
                "code": "flow_task_failure",
                "message": "Extra hidden schema with secret-token.",
                "secret_token": "must not leak",
            },
            "secret_token",
        ),
    ],
)
def test_parse_flow_run_error_sanitizes_corrupt_persisted_values(
    payload: object,
    leaked_text: str,
) -> None:
    error = parse_flow_run_error(payload)

    _assert_corrupt_run_error(error)
    serialized = json.dumps(dump_flow_run_error(error), sort_keys=True)
    assert leaked_text not in serialized


@pytest.mark.parametrize(
    "code",
    [
        "legacy_uncataloged_code",
        FlowApiErrorCode.FLOW_NOT_PUBLISHED.value,
    ],
)
def test_parse_flow_run_error_sanitizes_non_terminal_or_uncataloged_codes(
    code: str,
) -> None:
    error = parse_flow_run_error(
        {
            "schema_version": 1,
            "code": code,
            "message": "Stored before the run-error taxonomy was closed.",
            "source": "executor_failed",
        }
    )

    _assert_corrupt_run_error(error)
    serialized = json.dumps(dump_flow_run_error(error), sort_keys=True)
    assert code not in serialized


def test_parse_flow_run_error_accepts_terminal_string_codes() -> None:
    error = parse_flow_run_error(
        {
            "schema_version": 1,
            "code": FlowApiErrorCode.RUN_TASK_FAILURE.value,
            "message": "Task failed before run completion.",
            "source": "task_failure",
        }
    )

    assert error is not None
    assert error.code == FlowApiErrorCode.RUN_TASK_FAILURE
    assert dump_flow_run_error(error) == {
        "schema_version": 1,
        "code": FlowApiErrorCode.RUN_TASK_FAILURE.value,
        "message": "Task failed before run completion.",
        "source": "task_failure",
    }


def test_flow_run_read_model_sanitizes_corrupt_persisted_error_json() -> None:
    now = datetime.now(timezone.utc)

    run = FlowRun.model_validate(
        {
            "id": uuid4(),
            "flow_id": uuid4(),
            "flow_version": 1,
            "principal_type": PrincipalType.USER,
            "principal_user_id": uuid4(),
            "tenant_id": uuid4(),
            "trace_id": uuid4(),
            "revision": 1,
            "status": FlowRunStatus.FAILED,
            "error_json": "Step review_policy is invalid.",
            "created_at": now,
            "updated_at": now,
        }
    )

    _assert_corrupt_run_error(run.error)


def test_flow_run_error_requires_cataloged_code() -> None:
    with pytest.raises(ValidationError):
        FlowRunError(
            code="Invalid Code With Spaces",
            message="Invalid error code.",
            source=FlowRunLifecycleSource.INVALID_FLOW_DEFINITION,
        )


def test_flow_run_error_requires_terminal_code() -> None:
    with pytest.raises(ValidationError):
        FlowRunError(
            code=FlowApiErrorCode.FLOW_NOT_PUBLISHED,
            message="Request-time code cannot be used as a terminal run error.",
            source=FlowRunLifecycleSource.INVALID_FLOW_DEFINITION,
        )


def test_run_error_payload_invalid_code_is_terminal() -> None:
    assert FlowApiErrorCode.RUN_ERROR_PAYLOAD_INVALID in FLOW_RUN_TERMINAL_ERROR_CODES


def test_flow_run_error_from_source_truncates_unbounded_messages() -> None:
    error = FlowRunError.from_source(
        FlowRunLifecycleSource.EXECUTOR_FAILED,
        code=FlowApiErrorCode.RUN_TASK_FAILURE,
        message="x" * 5000,
    )

    assert len(error.message) == 4096
    assert error.message.endswith("... [truncated]")
