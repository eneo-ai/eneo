import inspect
import re
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint
from sqlalchemy.sql.schema import Column

from eneo.database.tables.flow_tables import (
    FlowStepAttempts,
    FlowStepResults,
    FlowSteps,
    FlowTemplateAssets,
)
from eneo.flows.domain.flow import FlowStepAttempt, FlowStepResult
from eneo.flows.enums import (
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
    FlowTemplateAssetStatus,
)


def _flow_step_result_payload() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "id": uuid4(),
        "flow_run_id": uuid4(),
        "flow_id": uuid4(),
        "tenant_id": uuid4(),
        "step_id": UUID("11111111-1111-4111-8111-111111111111"),
        "step_order": 1,
        "assistant_id": uuid4(),
        "current_attempt_no": 1,
        "input_payload_json": {"question": "What happened?"},
        "effective_prompt": "Summarize the input.",
        "output_payload_json": {"summary": "Done"},
        "model_parameters_json": {"temperature": 0.2},
        "num_tokens_input": 11,
        "num_tokens_output": 7,
        "status": FlowStepResultStatus.COMPLETED,
        "error_code": None,
        "error_message": None,
        "flow_step_execution_hash": "hash-1",
        "started_at": now,
        "finished_at": now,
        "created_at": now,
        "updated_at": now,
    }


def _flow_step_attempt_payload() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "id": uuid4(),
        "flow_run_id": uuid4(),
        "flow_id": uuid4(),
        "tenant_id": uuid4(),
        "step_id": UUID("22222222-2222-4222-8222-222222222222"),
        "step_order": 1,
        "attempt_no": 1,
        "rerun_operation_id": None,
        "predecessor_attempt_id": None,
        "superseded_by_attempt_id": None,
        "celery_task_id": "celery-1",
        "status": FlowStepAttemptStatus.COMPLETED,
        "error_code": None,
        "error_message": None,
        "requested_model": "gpt-4o-mini",
        "response_model": "gpt-4o-mini",
        "provider": "openai",
        "finish_reason": "stop",
        "provider_response_id": "resp_123",
        "num_tokens_input": 11,
        "num_tokens_output": 7,
        "provenance_json": {"schema_version": 1},
        "input_payload_json": {"question": "What happened?"},
        "output_payload_json": {"summary": "Done"},
        "flow_step_execution_hash": "hash-1",
        "started_at": now,
        "finished_at": now,
        "created_at": now,
        "updated_at": now,
    }


def _references_flow_steps(table_column: Column[object]) -> bool:
    return any(
        foreign_key.column.table.name == "flow_steps"
        for foreign_key in table_column.foreign_keys
    )


@pytest.mark.parametrize(
    ("table", "constraint_name", "enum_type", "canonical_values_name"),
    [
        (
            FlowSteps,
            "ck_flow_steps_input_type",
            FlowInputType,
            "FLOW_STEP_INPUT_TYPE_VALUES",
        ),
        (
            FlowSteps,
            "ck_flow_steps_output_mode",
            FlowOutputMode,
            "FLOW_STEP_OUTPUT_MODE_VALUES",
        ),
        (
            FlowSteps,
            "ck_flow_steps_output_type",
            FlowOutputType,
            "FLOW_STEP_OUTPUT_TYPE_VALUES",
        ),
        (
            FlowTemplateAssets,
            "ck_flow_template_assets_status",
            FlowTemplateAssetStatus,
            "FLOW_TEMPLATE_ASSET_STATUS_VALUES",
        ),
        (
            FlowStepResults,
            "ck_flow_step_results_status",
            FlowStepResultStatus,
            "FLOW_STEP_RESULT_STATUS_VALUES",
        ),
        (
            FlowStepAttempts,
            "ck_flow_step_attempts_status",
            FlowStepAttemptStatus,
            "FLOW_STEP_ATTEMPT_STATUS_VALUES",
        ),
    ],
)
def test_enum_backed_flow_check_values_follow_their_canonical_enums(
    table, constraint_name, enum_type, canonical_values_name
) -> None:
    constraint = next(
        constraint
        for constraint in table.__table__.constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name == constraint_name
    )

    assert tuple(re.findall(r"'([^']+)'", str(constraint.sqltext))) == tuple(
        item.value for item in enum_type
    )
    assert f"_check_values({canonical_values_name})" in inspect.getsource(table)


def test_runtime_step_result_step_id_is_snapshot_owned_not_draft_step_fk():
    step_id = FlowStepResults.__table__.columns["step_id"]

    assert step_id.nullable is False
    assert not _references_flow_steps(step_id)


def test_runtime_step_attempt_step_id_is_snapshot_owned_not_draft_step_fk():
    step_id = FlowStepAttempts.__table__.columns["step_id"]

    assert step_id.nullable is False
    assert not _references_flow_steps(step_id)


@pytest.mark.parametrize("step_id_shape", ["missing", None])
def test_flow_step_result_requires_snapshot_step_id(step_id_shape):
    payload = _flow_step_result_payload()
    if step_id_shape == "missing":
        payload.pop("step_id")
    else:
        payload["step_id"] = step_id_shape

    with pytest.raises(ValidationError):
        FlowStepResult(**payload)


def test_flow_step_result_preserves_failure_error_code():
    payload = _flow_step_result_payload()
    payload["status"] = FlowStepResultStatus.FAILED
    payload["error_code"] = "flow_step_execution_failed"
    payload["error_message"] = "Flow step 1 execution failed."

    result = FlowStepResult(**payload)

    assert result.error_code == "flow_step_execution_failed"


@pytest.mark.parametrize("step_id_shape", ["missing", None])
def test_flow_step_attempt_requires_snapshot_step_id(step_id_shape):
    payload = _flow_step_attempt_payload()
    if step_id_shape == "missing":
        payload.pop("step_id")
    else:
        payload["step_id"] = step_id_shape

    with pytest.raises(ValidationError):
        FlowStepAttempt(**payload)


def test_flow_steps_reject_legacy_text_document_pass_through_tuple() -> None:
    constraints = {
        constraint.name: str(constraint.sqltext)
        for constraint in FlowSteps.__table__.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name is not None
    }

    constraint_sql = constraints["ck_flow_steps_no_text_document_pass_through"]
    assert "input_type = 'text'" in constraint_sql
    assert "output_mode = 'pass_through'" in constraint_sql
    assert "output_type IN ('pdf','docx')" in constraint_sql


def test_flow_step_source_constraint_excludes_post_but_output_retains_post() -> None:
    constraints = {
        constraint.name: str(constraint.sqltext)
        for constraint in FlowSteps.__table__.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name is not None
    }

    input_source_sql = constraints["ck_flow_steps_input_source"]
    output_mode_sql = constraints["ck_flow_steps_output_mode"]

    assert "http_get" in input_source_sql
    assert "http_post" not in input_source_sql
    assert "http_post" in output_mode_sql
