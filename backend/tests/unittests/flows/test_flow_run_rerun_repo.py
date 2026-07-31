from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from eneo.authentication.principal_types import PrincipalType
from eneo.flows.domain.flow import (
    FlowRunStatus,
    FlowStepResultStatus,
    RerunStepInputOverride,
)
from eneo.flows.domain.flow_run_exceptions import (
    FlowRunNotFoundError,
    FlowRunPersistenceInvariantError,
)
from eneo.flows.domain.rerun_exceptions import (
    FlowRunRerunMultipleActiveOperationsError,
)
from eneo.flows.domain.run_step_input_exceptions import (
    FlowRunRuntimeUploadBindingRaceError,
)
from eneo.flows.flow_run_input_envelope import RerunInputOverride
from eneo.flows.flow_run_rerun_graph import RerunInvalidatedStep
from eneo.flows.infrastructure import flow_run_rerun_repo
from eneo.flows.infrastructure.flow_run_rerun_repo import FlowRunRerunRepository
from eneo.flows.principal import FlowPrincipal


@dataclass(frozen=True, slots=True)
class _RerunAcceptScenario:
    repo: FlowRunRerunRepository
    session: AsyncMock
    tenant_id: UUID
    flow_id: UUID
    run_id: UUID
    step_id: UUID
    run_row: SimpleNamespace
    current_result_row: SimpleNamespace


class _ScalarRows:
    def __init__(self, rows: list[object]):
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _ExecuteRows:
    def __init__(self, rows: list[object]):
        self._rows = rows

    def scalars(self) -> _ScalarRows:
        return _ScalarRows(self._rows)


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


def _prepare_completed_rerun_accept_scenario(monkeypatch) -> _RerunAcceptScenario:
    session = AsyncMock()
    repo = FlowRunRerunRepository(session=session)
    tenant_id = uuid4()
    flow_id = uuid4()
    run_id = uuid4()
    step_id = uuid4()
    run_row = SimpleNamespace(
        id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        revision=7,
        status=FlowRunStatus.COMPLETED.value,
        input_payload_json={},
    )
    current_result_row = SimpleNamespace(
        id=uuid4(),
        status=FlowStepResultStatus.COMPLETED.value,
    )
    monkeypatch.setattr(
        repo,
        "_get_rerun_operation_row",
        AsyncMock(side_effect=[None, None, None]),
    )
    monkeypatch.setattr(
        repo,
        "_current_step_results_by_step_id",
        AsyncMock(return_value={step_id: current_result_row}),
    )
    monkeypatch.setattr(
        repo,
        "_latest_completed_attempts_by_step_id",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        flow_run_rerun_repo, "next_step_attempt_no", AsyncMock(return_value=2)
    )
    return _RerunAcceptScenario(
        repo=repo,
        session=session,
        tenant_id=tenant_id,
        flow_id=flow_id,
        run_id=run_id,
        step_id=step_id,
        run_row=run_row,
        current_result_row=current_result_row,
    )


@pytest.mark.asyncio
async def test_get_active_rerun_operation_rejects_multiple_active_rows() -> None:
    session = AsyncMock()
    session.execute.return_value = _ExecuteRows([object(), object()])
    repo = FlowRunRerunRepository(session=session)
    run_id = uuid4()

    with pytest.raises(FlowRunRerunMultipleActiveOperationsError) as exc_info:
        await repo.get_active_rerun_operation(
            run_id=run_id,
            flow_id=uuid4(),
            tenant_id=uuid4(),
        )

    assert exc_info.value.flow_run_id == run_id


@pytest.mark.asyncio
async def test_accept_or_replay_rerun_operation_raises_flow_run_not_found_error(
    monkeypatch,
) -> None:
    session = AsyncMock()
    session.scalar.return_value = None
    repo = FlowRunRerunRepository(session=session)
    tenant_id = uuid4()
    flow_id = uuid4()
    run_id = uuid4()
    monkeypatch.setattr(
        repo,
        "_get_rerun_operation_row",
        AsyncMock(return_value=None),
    )

    with pytest.raises(FlowRunNotFoundError) as exc_info:
        await repo.accept_or_replay_rerun_operation(
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_run_id=run_id,
            rerun_step_id=uuid4(),
            rerun_step_order=1,
            request_fingerprint="fingerprint",
            expected_run_revision=7,
            reason="Refresh answer",
            rerun_input_override=RerunInputOverride(
                inline_payload_json=None,
                root_step_input=None,
            ),
            requested_by_principal=FlowPrincipal(
                principal_type=PrincipalType.USER,
                principal_user_id=uuid4(),
            ),
            invalidated_steps=[],
        )

    assert exc_info.value.run_id == run_id
    assert exc_info.value.tenant_id == tenant_id
    assert exc_info.value.flow_id == flow_id


@pytest.mark.asyncio
async def test_accept_or_replay_rerun_operation_raises_persistence_invariant_after_locked_update_returns_no_row(
    monkeypatch,
) -> None:
    scenario = _prepare_completed_rerun_accept_scenario(monkeypatch)
    operation_row = SimpleNamespace(id=uuid4())
    scenario.session.scalar.side_effect = [
        scenario.run_row,
        operation_row,
        operation_row,
        None,
    ]
    scenario.session.execute.return_value = SimpleNamespace()

    with pytest.raises(FlowRunPersistenceInvariantError) as exc_info:
        await scenario.repo.accept_or_replay_rerun_operation(
            tenant_id=scenario.tenant_id,
            flow_id=scenario.flow_id,
            flow_run_id=scenario.run_id,
            rerun_step_id=scenario.step_id,
            rerun_step_order=1,
            request_fingerprint="fingerprint",
            expected_run_revision=7,
            reason="Refresh answer",
            rerun_input_override=RerunInputOverride(
                inline_payload_json=None,
                root_step_input=None,
            ),
            requested_by_principal=FlowPrincipal(
                principal_type=PrincipalType.USER,
                principal_user_id=uuid4(),
            ),
            invalidated_steps=[
                RerunInvalidatedStep(
                    step_id=scenario.step_id,
                    step_order=1,
                    dependency_kinds=(),
                )
            ],
        )

    assert exc_info.value.operation == "rerun_flow_run_update"


@pytest.mark.asyncio
async def test_accept_or_replay_rerun_operation_raises_persistence_invariant_when_operation_insert_and_lookup_return_no_row(
    monkeypatch,
) -> None:
    scenario = _prepare_completed_rerun_accept_scenario(monkeypatch)
    scenario.session.scalar.side_effect = [scenario.run_row, None]
    scenario.session.execute.return_value = SimpleNamespace()

    with pytest.raises(FlowRunPersistenceInvariantError) as exc_info:
        await scenario.repo.accept_or_replay_rerun_operation(
            tenant_id=scenario.tenant_id,
            flow_id=scenario.flow_id,
            flow_run_id=scenario.run_id,
            rerun_step_id=scenario.step_id,
            rerun_step_order=1,
            request_fingerprint="fingerprint",
            expected_run_revision=7,
            reason="Refresh answer",
            rerun_input_override=RerunInputOverride(
                inline_payload_json=None,
                root_step_input=None,
            ),
            requested_by_principal=FlowPrincipal(
                principal_type=PrincipalType.USER,
                principal_user_id=uuid4(),
            ),
            invalidated_steps=[
                RerunInvalidatedStep(
                    step_id=scenario.step_id,
                    step_order=1,
                    dependency_kinds=(),
                )
            ],
        )

    assert exc_info.value.operation == "create_rerun_operation"
    assert exc_info.value.run_id == scenario.run_id
    assert exc_info.value.tenant_id == scenario.tenant_id
    assert exc_info.value.flow_id == scenario.flow_id


@pytest.mark.asyncio
async def test_accept_or_replay_existing_rerun_operation_raises_flow_run_not_found_when_parent_run_is_missing(
    monkeypatch,
) -> None:
    session = AsyncMock()
    repo = FlowRunRerunRepository(session=session)
    tenant_id = uuid4()
    flow_id = uuid4()
    run_id = uuid4()
    operation_row = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        flow_id=flow_id,
        flow_run_id=run_id,
    )
    session.scalar.return_value = None
    monkeypatch.setattr(
        repo,
        "_get_rerun_operation_row",
        AsyncMock(return_value=operation_row),
    )

    with pytest.raises(FlowRunNotFoundError) as exc_info:
        await repo.accept_or_replay_rerun_operation(
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_run_id=run_id,
            rerun_step_id=uuid4(),
            rerun_step_order=1,
            request_fingerprint="fingerprint",
            expected_run_revision=7,
            reason="Refresh answer",
            rerun_input_override=RerunInputOverride(
                inline_payload_json=None,
                root_step_input=None,
            ),
            requested_by_principal=FlowPrincipal(
                principal_type=PrincipalType.USER,
                principal_user_id=uuid4(),
            ),
            invalidated_steps=[],
        )

    assert exc_info.value.run_id == run_id
    assert exc_info.value.tenant_id == tenant_id
    assert exc_info.value.flow_id == flow_id


@pytest.mark.asyncio
async def test_rerun_accept_raises_runtime_upload_binding_race_payload(
    monkeypatch,
) -> None:
    scenario = _prepare_completed_rerun_accept_scenario(monkeypatch)
    file_id = uuid4()
    operation_row = SimpleNamespace(id=uuid4())
    scenario.session.scalar.side_effect = [scenario.run_row, operation_row]
    scenario.session.execute.side_effect = [
        SimpleNamespace(),
        _integrity_error_for_constraint("fk_flow_run_step_input_files_runtime_upload"),
    ]

    with pytest.raises(FlowRunRuntimeUploadBindingRaceError) as exc_info:
        await scenario.repo.accept_or_replay_rerun_operation(
            tenant_id=scenario.tenant_id,
            flow_id=scenario.flow_id,
            flow_run_id=scenario.run_id,
            rerun_step_id=scenario.step_id,
            rerun_step_order=1,
            request_fingerprint="fingerprint",
            expected_run_revision=7,
            reason="Refresh answer",
            rerun_input_override=RerunInputOverride(
                inline_payload_json=None,
                root_step_input=RerunStepInputOverride(
                    step_id=scenario.step_id,
                    file_ids=(file_id,),
                ),
            ),
            requested_by_principal=FlowPrincipal(
                principal_type=PrincipalType.USER,
                principal_user_id=uuid4(),
            ),
            invalidated_steps=[
                RerunInvalidatedStep(
                    step_id=scenario.step_id,
                    step_order=1,
                    dependency_kinds=(),
                )
            ],
        )

    assert exc_info.value.step_id == scenario.step_id
    assert exc_info.value.file_ids == (file_id,)
