from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.sql.schema import Column

from intric.database.tables.flow_tables import FlowStepAttempts, FlowStepResults
from intric.flows.domain.flow import FlowStepAttempt, FlowStepResult
from intric.flows.enums import FlowStepAttemptStatus, FlowStepResultStatus


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


@pytest.mark.parametrize("step_id_shape", ["missing", None])
def test_flow_step_attempt_requires_snapshot_step_id(step_id_shape):
    payload = _flow_step_attempt_payload()
    if step_id_shape == "missing":
        payload.pop("step_id")
    else:
        payload["step_id"] = step_id_shape

    with pytest.raises(ValidationError):
        FlowStepAttempt(**payload)
