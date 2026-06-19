from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from intric.flows import FlowFactory
from intric.flows.domain.flow_run_exceptions import (
    FlowRunNotFoundError,
    FlowRunPersistenceInvariantError,
)
from intric.flows.domain.run_step_input_exceptions import (
    FlowRunRuntimeUploadBindingRaceError,
)
from intric.flows.infrastructure.flow_run_repo import FlowRunRepository


class _Diagnostic:
    def __init__(self, constraint_name: str):
        self.constraint_name = constraint_name


class _ConstraintOrigin(Exception):
    def __init__(self, constraint_name: str):
        super().__init__(constraint_name)
        self.diag = _Diagnostic(constraint_name)


def _integrity_error_for_constraint(constraint_name: str) -> IntegrityError:
    return IntegrityError(
        statement="INSERT INTO flow_run_step_input_files",
        params={},
        orig=_ConstraintOrigin(constraint_name),
    )


@pytest.mark.asyncio
async def test_get_raises_flow_run_not_found_error() -> None:
    session = AsyncMock()
    session.scalar.return_value = None
    repo = FlowRunRepository(session=session, factory=FlowFactory())
    run_id = uuid4()
    tenant_id = uuid4()

    with pytest.raises(FlowRunNotFoundError) as exc_info:
        await repo.get(run_id=run_id, tenant_id=tenant_id)

    assert exc_info.value.run_id == run_id
    assert exc_info.value.tenant_id == tenant_id
    assert exc_info.value.flow_id is None


@pytest.mark.asyncio
async def test_create_raises_persistence_invariant_when_insert_returns_no_row() -> None:
    session = AsyncMock()
    session.scalar.return_value = None
    repo = FlowRunRepository(session=session, factory=FlowFactory())

    with pytest.raises(FlowRunPersistenceInvariantError) as exc_info:
        await repo.create(
            flow_id=uuid4(),
            flow_version=1,
            principal_user_id=uuid4(),
            tenant_id=uuid4(),
            input_payload_json={},
            preseed_steps=[],
        )

    assert exc_info.value.operation == "create_flow_run"


@pytest.mark.asyncio
async def test_create_or_get_attempt_started_raises_persistence_invariant_when_insert_and_lookup_return_no_row() -> (
    None
):
    session = AsyncMock()
    session.scalar.side_effect = [None, None]
    repo = FlowRunRepository(session=session, factory=FlowFactory())
    run_id = uuid4()
    tenant_id = uuid4()
    flow_id = uuid4()

    with pytest.raises(FlowRunPersistenceInvariantError) as exc_info:
        await repo.create_or_get_attempt_started(
            run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            step_id=uuid4(),
            step_order=1,
            attempt_no=1,
            celery_task_id=None,
        )

    assert exc_info.value.operation == "create_flow_step_attempt"
    assert exc_info.value.run_id == run_id
    assert exc_info.value.tenant_id == tenant_id
    assert exc_info.value.flow_id == flow_id


@pytest.mark.asyncio
async def test_create_raises_runtime_upload_binding_race_payload() -> None:
    session = AsyncMock()
    session.scalar.return_value = SimpleNamespace(id=uuid4())
    session.execute.side_effect = _integrity_error_for_constraint(
        "fk_flow_run_step_input_files_runtime_upload"
    )
    repo = FlowRunRepository(session=session, factory=FlowFactory())
    flow_id = uuid4()
    tenant_id = uuid4()
    step_id = uuid4()
    file_id = uuid4()

    with pytest.raises(FlowRunRuntimeUploadBindingRaceError) as exc_info:
        await repo.create(
            flow_id=flow_id,
            flow_version=1,
            principal_user_id=uuid4(),
            tenant_id=tenant_id,
            input_payload_json={},
            preseed_steps=[],
            step_input_files=[
                {"step_id": step_id, "step_order": 1, "file_ids": [file_id]}
            ],
        )

    assert exc_info.value.step_id == step_id
    assert exc_info.value.file_ids == (file_id,)


@pytest.mark.asyncio
async def test_create_reraises_unrelated_step_input_integrity_error() -> None:
    error = _integrity_error_for_constraint(
        "uq_flow_run_step_input_files_run_step_attempt_file"
    )
    session = AsyncMock()
    session.scalar.return_value = SimpleNamespace(id=uuid4())
    session.execute.side_effect = error
    repo = FlowRunRepository(session=session, factory=FlowFactory())

    with pytest.raises(IntegrityError) as exc_info:
        await repo.create(
            flow_id=uuid4(),
            flow_version=1,
            principal_user_id=uuid4(),
            tenant_id=uuid4(),
            input_payload_json={},
            preseed_steps=[],
            step_input_files=[
                {"step_id": uuid4(), "step_order": 1, "file_ids": [uuid4()]}
            ],
        )

    assert exc_info.value is error
