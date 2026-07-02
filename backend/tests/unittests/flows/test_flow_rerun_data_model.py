from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, Index, UniqueConstraint

from eneo.authentication.auth_models import FlowServicePrincipalActorPublic
from eneo.authentication.principal_types import PrincipalType
from eneo.database.tables.flow_tables import (
    FLOW_RUN_RERUN_INVALIDATION_ROLE_VALUES,
    FLOW_RUN_RERUN_OPERATION_STATUS_VALUES,
    FlowRunRerunInvalidatedSteps,
    FlowRunRerunOperations,
    FlowRuns,
    FlowStepAttempts,
    FlowStepResults,
)
from eneo.flows.api.flow_models import FlowRunRerunOperationPublic
from eneo.flows.domain.flow import FlowRunRerunOperation, RerunStepInputOverride
from eneo.flows.enums import (
    FlowRunRerunInvalidationRole,
    FlowRunRerunOperationStatus,
)


def _constraint_names(table: object) -> set[str]:
    return {
        constraint.name or ""
        for constraint in table.__table__.constraints
        if constraint.name is not None
    }


def _unique_columns(table: object, constraint_name: str) -> tuple[str, ...]:
    for constraint in table.__table__.constraints:
        if (
            isinstance(constraint, UniqueConstraint)
            and constraint.name == constraint_name
        ):
            return tuple(column.name for column in constraint.columns)
    raise AssertionError(f"Unique constraint {constraint_name} was not found.")


def _check_constraint_sql(table: object, constraint_name: str) -> str:
    for constraint in table.__table__.constraints:
        if (
            isinstance(constraint, CheckConstraint)
            and constraint.name == constraint_name
        ):
            return str(constraint.sqltext)
    raise AssertionError(f"Check constraint {constraint_name} was not found.")


def _index_by_name(table: object, index_name: str) -> Index:
    for index in table.__table__.indexes:
        if index.name == index_name:
            return index
    raise AssertionError(f"Index {index_name} was not found.")


def _service_principal_actor() -> FlowServicePrincipalActorPublic:
    return FlowServicePrincipalActorPublic(
        id=uuid4(),
        display_name="Runtime service principal",
    )


def _rerun_operation_public_payload() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "flow_id": uuid4(),
        "flow_run_id": uuid4(),
        "rerun_step_id": uuid4(),
        "rerun_step_order": 1,
        "root_attempt_no": 2,
        "status": FlowRunRerunOperationStatus.QUEUED,
        "request_fingerprint": "fingerprint",
        "expected_run_revision": 1,
        "accepted_run_revision": 1,
        "reason": "Refresh output",
        "root_step_input_override_requested": False,
        "requested_by_principal_type": PrincipalType.SERVICE_KEY,
        "requested_by_service_principal": _service_principal_actor(),
        "created_at": now,
        "updated_at": now,
    }


def _rerun_operation_domain_payload() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "flow_id": uuid4(),
        "flow_run_id": uuid4(),
        "rerun_step_id": uuid4(),
        "rerun_step_order": 1,
        "root_attempt_no": 2,
        "root_attempt_id": None,
        "status": FlowRunRerunOperationStatus.QUEUED,
        "request_fingerprint": "fingerprint",
        "expected_run_revision": 1,
        "accepted_run_revision": 1,
        "reason": "Refresh output",
        "input_payload_json": None,
        "root_step_input_override_requested": False,
        "root_step_input_override": None,
        "requested_by_principal_type": PrincipalType.USER,
        "requested_by_user_id": uuid4(),
        "requested_by_service_id": None,
        "failure_code": None,
        "failure_message": None,
        "started_at": None,
        "finished_at": None,
        "created_at": now,
        "updated_at": now,
    }


def test_rerun_operation_public_projects_input_payload_from_internal_column():
    payload = _rerun_operation_public_payload()
    payload["input_payload_json"] = {"case_id": "CASE-1"}

    operation = FlowRunRerunOperationPublic.model_validate(payload)
    dumped = operation.model_dump(mode="json")

    assert operation.input_payload == {"case_id": "CASE-1"}
    assert "input_payload" in dumped
    assert "input_payload_json" not in dumped


def test_rerun_operation_public_projects_explicit_file_override():
    step_id = uuid4()
    file_id = uuid4()
    payload = _rerun_operation_public_payload()
    payload["root_step_input_override"] = {
        "step_id": str(step_id),
        "file_ids": [str(file_id)],
    }
    payload["root_step_input_override_requested"] = True

    operation = FlowRunRerunOperationPublic.model_validate(payload)

    assert operation.root_step_input_override_requested is True
    assert operation.root_step_input_override is not None
    assert operation.root_step_input_override.step_id == step_id
    assert operation.root_step_input_override.file_ids == [file_id]


def test_rerun_operation_public_projects_explicit_empty_override():
    step_id = uuid4()
    payload = _rerun_operation_public_payload()
    payload["root_step_input_override"] = {"step_id": str(step_id), "file_ids": []}
    payload["root_step_input_override_requested"] = True

    operation = FlowRunRerunOperationPublic.model_validate(payload)

    assert operation.root_step_input_override_requested is True
    assert operation.root_step_input_override is not None
    assert operation.root_step_input_override.step_id == step_id
    assert operation.root_step_input_override.file_ids == []


def test_rerun_operation_public_keeps_inherited_override_empty():
    payload = _rerun_operation_public_payload()

    operation = FlowRunRerunOperationPublic.model_validate(payload)

    assert operation.root_step_input_override_requested is False
    assert operation.root_step_input_override is None


def test_rerun_operation_public_rejects_contradictory_override_intent():
    payload = _rerun_operation_public_payload()
    payload["root_step_input_override_requested"] = True

    with pytest.raises(ValueError, match="root_step_input_override must be present"):
        FlowRunRerunOperationPublic.model_validate(payload)


def test_rerun_operation_domain_rejects_contradictory_override_intent():
    payload = _rerun_operation_domain_payload()
    payload["root_step_input_override_requested"] = True

    with pytest.raises(
        ValidationError, match="root_step_input_override must be present"
    ):
        FlowRunRerunOperation.model_validate(payload)


def test_rerun_operation_domain_rejects_mismatched_override_step_id():
    payload = _rerun_operation_domain_payload()
    payload["root_step_input_override_requested"] = True
    payload["root_step_input_override"] = RerunStepInputOverride(
        step_id=uuid4(),
        file_ids=(),
    )

    with pytest.raises(
        ValidationError,
        match="root_step_input_override.step_id must match rerun_step_id",
    ):
        FlowRunRerunOperation.model_validate(payload)


def test_rerun_operation_public_projects_from_attribute_object():
    step_id = uuid4()
    file_id = uuid4()
    payload = _rerun_operation_public_payload()
    payload["requested_by_principal_type"] = PrincipalType.USER
    payload["requested_by_user_id"] = uuid4()
    payload["requested_by_service_principal"] = None
    payload["input_payload_json"] = {"case_id": "CASE-2"}
    payload["root_step_input_override"] = {
        "step_id": str(step_id),
        "file_ids": [str(file_id)],
    }
    payload["root_step_input_override_requested"] = True

    operation = FlowRunRerunOperationPublic.model_validate(SimpleNamespace(**payload))

    assert operation.input_payload == {"case_id": "CASE-2"}
    assert operation.root_step_input_override is not None
    assert operation.root_step_input_override.step_id == step_id
    assert operation.root_step_input_override.file_ids == [file_id]


def test_rerun_operation_public_projects_typed_override_from_attribute_object():
    step_id = uuid4()
    file_id = uuid4()
    payload = _rerun_operation_public_payload()
    payload["root_step_input_override"] = RerunStepInputOverride(
        step_id=step_id,
        file_ids=(file_id,),
    )
    payload["root_step_input_override_requested"] = True

    operation = FlowRunRerunOperationPublic.model_validate(SimpleNamespace(**payload))

    assert operation.root_step_input_override is not None
    assert operation.root_step_input_override.step_id == step_id
    assert operation.root_step_input_override.file_ids == [file_id]


def test_rerun_status_and_role_values_are_canonical_enum_values():
    assert FLOW_RUN_RERUN_OPERATION_STATUS_VALUES == tuple(
        item.value for item in FlowRunRerunOperationStatus
    )
    assert FLOW_RUN_RERUN_INVALIDATION_ROLE_VALUES == tuple(
        item.value for item in FlowRunRerunInvalidationRole
    )


def test_rerun_operation_public_accepts_service_principal_actor_shape():
    operation = FlowRunRerunOperationPublic.model_validate(
        _rerun_operation_public_payload()
    )

    assert operation.requested_by_principal_type == PrincipalType.SERVICE_KEY
    assert operation.requested_by_service_principal is not None
    assert operation.requested_by_user_id is None


def test_rerun_operation_public_rejects_service_principal_without_summary():
    payload = _rerun_operation_public_payload()
    payload["requested_by_service_principal"] = None

    with pytest.raises(ValidationError, match="requested_by service principal"):
        FlowRunRerunOperationPublic.model_validate(payload)


def test_rerun_operation_public_rejects_mixed_requester_actor_shape():
    payload = _rerun_operation_public_payload()
    payload["requested_by_user_id"] = uuid4()

    with pytest.raises(ValidationError, match="requested_by service principal"):
        FlowRunRerunOperationPublic.model_validate(payload)


def test_run_revision_and_current_attempt_projection_columns_exist():
    revision = FlowRuns.__table__.columns["revision"]
    current_attempt_no = FlowStepResults.__table__.columns["current_attempt_no"]

    assert revision.nullable is False
    assert str(revision.server_default.arg) == "1"
    assert current_attempt_no.nullable is True
    assert str(current_attempt_no.server_default.arg) == "1"


def test_rerun_operation_table_owns_request_identity_and_status():
    assert {
        "tenant_id",
        "flow_id",
        "flow_run_id",
        "rerun_step_id",
        "root_attempt_no",
        "status",
        "request_fingerprint",
        "expected_run_revision",
        "accepted_run_revision",
        "reason",
        "root_step_input_override_requested",
        "requested_by_principal_type",
        "requested_by_user_id",
        "requested_by_service_id",
    }.issubset(FlowRunRerunOperations.__table__.columns.keys())
    assert _unique_columns(
        FlowRunRerunOperations,
        "uq_flow_run_rerun_operations_request_fingerprint",
    ) == ("tenant_id", "flow_run_id", "request_fingerprint")
    assert "ck_flow_run_rerun_operations_status" in _constraint_names(
        FlowRunRerunOperations
    )
    requester_constraint = _check_constraint_sql(
        FlowRunRerunOperations,
        "ck_flow_run_rerun_operations_requester_principal",
    )
    assert "requested_by_principal_type = 'user'" in requester_constraint
    assert "requested_by_service_id IS NOT NULL" in requester_constraint
    assert FlowRunRerunOperations.__table__.columns["failure_code"].type.length == 64
    override_column = FlowRunRerunOperations.__table__.columns[
        "root_step_input_override_requested"
    ]
    assert override_column.nullable is False
    assert override_column.server_default is None
    active_index = _index_by_name(
        FlowRunRerunOperations,
        "uq_flow_run_rerun_operations_one_active_per_run",
    )
    assert active_index.unique is True
    assert tuple(column.name for column in active_index.columns) == ("flow_run_id",)
    assert (
        str(active_index.dialect_options["postgresql"]["where"])
        == "status IN ('queued', 'running')"
    )


def test_new_rerun_foreign_key_names_fit_postgres_identifier_limit():
    new_attempt_fk_columns = {
        "rerun_operation_id",
        "predecessor_attempt_id",
        "superseded_by_attempt_id",
    }
    for table in (
        FlowRunRerunOperations,
        FlowStepAttempts,
        FlowRunRerunInvalidatedSteps,
    ):
        for foreign_key in table.__table__.foreign_key_constraints:
            if table is FlowStepAttempts and not new_attempt_fk_columns.intersection(
                foreign_key.columns.keys()
            ):
                continue
            assert foreign_key.name is not None
            assert len(foreign_key.name) <= 63


def test_step_attempts_have_rerun_lineage_and_payload_snapshots():
    assert {
        "rerun_operation_id",
        "predecessor_attempt_id",
        "superseded_by_attempt_id",
        "input_payload_json",
        "output_payload_json",
        "flow_step_execution_hash",
    }.issubset(FlowStepAttempts.__table__.columns.keys())


def test_invalidated_steps_table_links_operation_and_attempt_lineage():
    assert {
        "operation_id",
        "tenant_id",
        "flow_id",
        "flow_run_id",
        "step_id",
        "invalidation_order",
        "role",
        "dependency_sources_json",
        "prior_step_result_id",
        "prior_attempt_id",
        "new_attempt_no",
        "new_attempt_id",
    }.issubset(FlowRunRerunInvalidatedSteps.__table__.columns.keys())
    assert _unique_columns(
        FlowRunRerunInvalidatedSteps,
        "uq_flow_run_rerun_invalidated_steps_operation_step",
    ) == ("operation_id", "step_id")
    assert _unique_columns(
        FlowRunRerunInvalidatedSteps,
        "uq_flow_run_rerun_invalidated_steps_operation_order",
    ) == ("operation_id", "invalidation_order")
    assert "ck_flow_run_rerun_invalidated_steps_role" in _constraint_names(
        FlowRunRerunInvalidatedSteps
    )
