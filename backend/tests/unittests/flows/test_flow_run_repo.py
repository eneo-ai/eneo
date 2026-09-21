from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from eneo.flows.domain.flow import FlowRunStatus, FlowStepResult
from eneo.flows.domain.flow_run_exceptions import (
    FlowRunNotFoundError,
    FlowRunPersistenceInvariantError,
)
from eneo.flows.domain.run_step_input_exceptions import (
    FlowRunRuntimeUploadBindingRaceError,
)
from eneo.flows.domain.step_output import FileBackedStepText
from eneo.flows.enums import FlowStepResultStatus
from eneo.flows.flow_run_input_envelope import FlowRunInputEnvelopePatch
from eneo.flows.flow_run_step_result_file import FlowStepResultFileReference
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository


class _Diagnostic:
    def __init__(self, constraint_name: str):
        self.constraint_name = constraint_name


@pytest.mark.asyncio
async def test_claim_initializes_execution_heartbeat_in_the_same_update() -> None:
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(rowcount=1)
    repo = FlowRunRepository(session=session)
    run_id, tenant_id = uuid4(), uuid4()

    assert await repo.mark_running_if_claimable(
        run_id=run_id, tenant_id=tenant_id, expected_revision=7
    )

    assert session.execute.await_count == 1
    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "execution_heartbeat_at=clock_timestamp()" in str(compiled)
    assert run_id in compiled.params.values()
    assert tenant_id in compiled.params.values()
    assert 7 in compiled.params.values()


@pytest.mark.asyncio
async def test_heartbeat_renewal_is_fenced_and_does_not_touch_run_history() -> None:
    from eneo.flows.infrastructure.flow_run_repo import FlowRunExecutionOwner

    session = AsyncMock()
    owner = FlowRunExecutionOwner(uuid4(), uuid4(), 7)
    rows = MagicMock()
    rows.all.return_value = [(owner.run_id, owner.tenant_id, owner.revision)]
    session.execute.return_value = rows
    repo = FlowRunRepository(session=session)

    assert await repo.renew_execution_heartbeats(owners=[owner]) == {owner}

    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "execution_heartbeat_at=clock_timestamp()" in sql
    assert "updated_at=flow_runs.updated_at" in sql
    assert "(flow_runs.id, flow_runs.tenant_id, flow_runs.revision) IN" in sql
    assert "flow_runs.status =" in sql
    assert "flow_runs.execution_heartbeat_at > clock_timestamp() -" in sql
    assert "revision=" not in sql


@pytest.mark.asyncio
async def test_stale_discovery_has_one_payload_free_global_budget() -> None:
    session = AsyncMock()
    rows = MagicMock()
    rows.all.return_value = []
    session.execute.return_value = rows
    repo = FlowRunRepository(session=session)

    assert await repo.list_recovery_candidates(limit=3) == []

    statement = session.execute.await_args.args[0]
    assert list(statement.selected_columns.keys()) == [
        "id",
        "tenant_id",
        "revision",
        "anchor_at",
        "kind",
        "checkpoint_id",
    ]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "flow_runs.execution_heartbeat_at <= statement_timestamp() -" in sql
    assert "NOT (EXISTS" in sql
    assert "ORDER BY recovery.anchor_at ASC, recovery.id ASC" in sql
    assert statement._limit_clause.value == 3


@pytest.mark.asyncio
async def test_stale_terminal_update_rechecks_revision_heartbeat_and_delivery() -> None:
    session = AsyncMock()
    session.scalar.return_value = None
    repo = FlowRunRepository(session=session)

    assert (
        await repo.terminalize_run_status(
            run_id=uuid4(),
            tenant_id=uuid4(),
            target_status=FlowRunStatus.FAILED,
            stale_running_revision=7,
        )
        is None
    )

    assert session.scalar.await_count == 2
    lock = session.scalar.await_args_list[0].args[0]
    lock_sql = str(lock.compile(dialect=postgresql.dialect()))
    assert lock.is_select
    assert "FOR UPDATE" in lock_sql
    assert "flow_runs.tenant_id =" in lock_sql
    assert "EXISTS" not in lock_sql
    statement = session.scalar.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "flow_runs.revision =" in sql
    assert "flow_runs.execution_heartbeat_at <= statement_timestamp() -" in sql
    assert "NOT (EXISTS" in sql
    assert "flow_run_webhook_deliveries.tenant_id = flow_runs.tenant_id" in sql


@pytest.mark.asyncio
async def test_retained_input_snapshot_selects_only_file_identities():
    session = AsyncMock()
    rows = MagicMock()
    file_ids = [uuid4(), uuid4()]
    rows.scalars.return_value.all.return_value = file_ids
    session.execute.return_value = rows
    repo = FlowRunRepository(session=session)
    run_id, tenant_id = uuid4(), uuid4()

    result = await repo.list_retained_input_file_ids(run_id=run_id, tenant_id=tenant_id)

    assert result == file_ids
    statement = session.execute.await_args.args[0]
    assert list(statement.selected_columns.keys()) == ["file_id"]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "flow_step_results.current_attempt_no" in sql
    assert "coalesce(" in sql
    assert "input_payload_json" not in sql
    assert "output_payload_json" not in sql
    assert run_id in compiled.params.values()
    assert tenant_id in compiled.params.values()


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


def _step_result(status: FlowStepResultStatus) -> FlowStepResult:
    now = datetime.now(timezone.utc)
    return FlowStepResult(
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        input_payload_json={},
        effective_prompt="Prompt",
        output_payload_json={},
        model_parameters_json={},
        num_tokens_input=1,
        num_tokens_output=1,
        status=status,
        error_message=None,
        flow_step_execution_hash="hash",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.parametrize("outcome", ["failed", "inline", "transformed", "reused"])
async def test_transcript_file_ownership_survives_step_outcome(outcome):
    session = AsyncMock()
    repo = FlowRunRepository(session=session)
    result = _step_result(FlowStepResultStatus.RUNNING).model_copy(
        update={"current_attempt_no": None}
    )
    transcript = FileBackedStepText(
        preview="raw",
        inline_text_bytes=3,
        full_text_bytes=4096,
        file_id=uuid4(),
        checksum="a" * 64,
        source_step_id=result.step_id,
        source_attempt_no=2,
    )
    session.scalar.side_effect = [{}, result]
    payload = await repo.update_input_payload(
        run_id=result.flow_run_id,
        tenant_id=result.tenant_id,
        input_payload_patch=FlowRunInputEnvelopePatch.transcription(
            transcript=transcript
        ),
    )
    assert payload["transkribering"] == transcript.model_dump(mode="json")
    inserts = [
        call.args[0]
        for call in session.execute.await_args_list
        if call.args[0].is_insert
        and call.args[0].table.name == "flow_run_step_result_files"
    ]
    assert len(inserts) == 1
    registered = inserts[0].compile(dialect=postgresql.dialect()).params
    assert registered["file_id_m0"] == transcript.file_id
    assert registered["flow_run_id_m0"] == result.flow_run_id
    assert registered["tenant_id_m0"] == result.tenant_id
    assert registered["step_result_id_m0"] == result.id
    assert registered["attempt_no_m0"] == 2
    source_query = str(
        session.scalar.await_args.args[0].compile(dialect=postgresql.dialect())
    )
    assert "flow_step_results.tenant_id =" in source_query
    assert "flow_step_results.flow_run_id =" in source_query
    assert "flow_step_results.step_id =" in source_query
    assert "flow_step_attempts.attempt_no =" in source_query

    result = result.model_copy(
        update={
            "status": FlowStepResultStatus.FAILED
            if outcome == "failed"
            else FlowStepResultStatus.COMPLETED,
            "input_payload_json": {
                "runtime_input": {"text": transcript.model_dump(mode="json")}
            },
            "output_payload_json": {"text": "ok"},
        }
    )
    output_file_id = transcript.file_id if outcome == "reused" else uuid4()
    references = (
        [FlowStepResultFileReference(file_id=output_file_id, source="generated_output")]
        if outcome in {"reused", "transformed"}
        else []
    )
    session.scalar.side_effect = None
    session.scalar.return_value = result
    session.execute.reset_mock()
    await repo.save_step_result(
        flow_run_id=result.flow_run_id,
        result=result,
        tenant_id=result.tenant_id,
        attempt_no=2,
        result_file_references=None if outcome == "failed" else references,
    )
    if outcome == "failed":
        session.execute.assert_not_awaited()
        return
    final_insert = session.execute.await_args.args[0]
    assert final_insert.is_insert
    final_params = final_insert.compile(dialect=postgresql.dialect()).params
    assert {
        value for key, value in final_params.items() if key.startswith("file_id_")
    } == {
        transcript.file_id,
        *(reference.file_id for reference in references),
    }


@pytest.mark.asyncio
async def test_get_raises_flow_run_not_found_error() -> None:
    session = AsyncMock()
    session.scalar.return_value = None
    repo = FlowRunRepository(session=session)
    run_id = uuid4()
    tenant_id = uuid4()

    with pytest.raises(FlowRunNotFoundError) as exc_info:
        await repo.get(run_id=run_id, tenant_id=tenant_id)

    assert exc_info.value.run_id == run_id
    assert exc_info.value.tenant_id == tenant_id
    assert exc_info.value.flow_id is None


@pytest.mark.asyncio
async def test_get_status_selects_only_lifecycle_and_authorization_columns() -> None:
    session = AsyncMock()
    query_result = MagicMock()
    query_result.mappings.return_value.one_or_none.return_value = None
    session.execute.return_value = query_result
    repo = FlowRunRepository(session=session)

    with pytest.raises(FlowRunNotFoundError):
        await repo.get_status(run_id=uuid4(), tenant_id=uuid4())

    statement = session.execute.await_args.args[0]
    sql = " ".join(str(statement.compile(dialect=postgresql.dialect())).split())
    assert "flow_runs.principal_user_id" in sql
    assert "flow_runs.principal_service_id" in sql
    assert "flow_runs.input_payload_json" not in sql
    assert "flow_runs.output_payload_json" not in sql
    assert "flow_runs.error_json" not in sql
    assert "flow_runs.run_label" not in sql


@pytest.mark.asyncio
async def test_list_statuses_never_selects_run_content_columns() -> None:
    session = AsyncMock()
    query_result = MagicMock()
    query_result.mappings.return_value.all.return_value = []
    session.execute.return_value = query_result
    repo = FlowRunRepository(session=session)

    result = await repo.list_statuses(tenant_id=uuid4(), limit=50, offset=0)

    assert result == []
    statement = session.execute.await_args.args[0]
    sql = " ".join(str(statement.compile(dialect=postgresql.dialect())).split())
    assert "flow_runs.principal_user_id" in sql
    assert "flow_runs.principal_service_id" in sql
    assert "flow_runs.input_payload_json" not in sql
    assert "flow_runs.output_payload_json" not in sql
    assert "flow_runs.error_json" not in sql
    assert "flow_runs.run_label" not in sql
    assert "ORDER BY flow_runs.created_at DESC, flow_runs.id DESC" in sql


@pytest.mark.asyncio
async def test_get_step_attempt_is_scoped_to_tenant_run_step_and_attempt() -> None:
    session = AsyncMock()
    session.scalar.return_value = None
    repo = FlowRunRepository(session=session)
    run_id = uuid4()
    tenant_id = uuid4()
    step_id = uuid4()

    attempt = await repo.get_step_attempt(
        run_id=run_id,
        tenant_id=tenant_id,
        step_id=step_id,
        attempt_no=3,
    )

    assert attempt is None
    statement = session.scalar.await_args.args[0]
    sql = " ".join(str(statement.compile(dialect=postgresql.dialect())).split())
    assert "FROM flow_step_attempts" in sql
    assert "flow_step_attempts.flow_run_id =" in sql
    assert "flow_step_attempts.tenant_id =" in sql
    assert "flow_step_attempts.step_id =" in sql
    assert "flow_step_attempts.attempt_no =" in sql


@pytest.mark.asyncio
async def test_list_step_results_by_orders_reads_only_named_upstream_steps() -> None:
    session = AsyncMock()
    query_result = MagicMock()
    query_result.scalars.return_value.all.return_value = []
    session.execute.return_value = query_result
    repo = FlowRunRepository(session=session)
    run_id = uuid4()
    tenant_id = uuid4()

    results = await repo.list_step_results_by_orders(
        run_id=run_id,
        tenant_id=tenant_id,
        step_orders=(4, 2, 4),
    )

    assert results == []
    statement = session.execute.await_args.args[0]
    sql = " ".join(str(statement.compile(dialect=postgresql.dialect())).split())
    assert "FROM flow_step_results" in sql
    assert "flow_step_results.flow_run_id =" in sql
    assert "flow_step_results.tenant_id =" in sql
    assert "flow_step_results.step_order IN" in sql
    assert "ORDER BY flow_step_results.step_order ASC" in sql


@pytest.mark.asyncio
async def test_save_step_result_requires_attempt_for_completed_result() -> None:
    session = AsyncMock()
    repo = FlowRunRepository(session=session)

    with pytest.raises(
        ValueError,
        match="attempt_no is required for completed Flow step results",
    ):
        await repo.save_step_result(
            flow_run_id=uuid4(),
            result=_step_result(FlowStepResultStatus.COMPLETED),
            tenant_id=uuid4(),
            attempt_no=None,
        )

    session.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_step_result_requires_attempt_for_result_files() -> None:
    session = AsyncMock()
    repo = FlowRunRepository(session=session)

    with pytest.raises(
        ValueError,
        match="attempt_no is required for Flow step result files",
    ):
        await repo.save_step_result(
            flow_run_id=uuid4(),
            result=_step_result(FlowStepResultStatus.FAILED),
            tenant_id=uuid4(),
            attempt_no=None,
            result_file_references=[
                FlowStepResultFileReference(
                    file_id=uuid4(),
                    source="generated_output",
                )
            ],
        )

    session.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_step_result_guards_insert_and_update_with_active_parent() -> None:
    session = AsyncMock()
    session.scalar.return_value = None
    repo = FlowRunRepository(session=session)
    result = _step_result(FlowStepResultStatus.PENDING)

    saved = await repo.save_step_result(
        flow_run_id=result.flow_run_id,
        result=result,
        tenant_id=result.tenant_id,
        attempt_no=None,
    )

    assert saved is None
    statement = session.scalar.await_args.args[0]
    sql = " ".join(str(statement.compile(dialect=postgresql.dialect())).split())
    insert_arm, conflict_arm = sql.split(" ON CONFLICT ", maxsplit=1)
    assert "INSERT INTO flow_step_results" in insert_arm
    assert " SELECT " in insert_arm
    assert " WHERE EXISTS (SELECT " in insert_arm
    assert "flow_runs.status IN" in insert_arm
    assert "DO UPDATE SET" in conflict_arm
    assert "WHERE EXISTS (SELECT " in conflict_arm
    assert "flow_runs.status IN" in conflict_arm


@pytest.mark.asyncio
async def test_create_raises_persistence_invariant_when_insert_returns_no_row() -> None:
    session = AsyncMock()
    session.scalar.return_value = None
    repo = FlowRunRepository(session=session)

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
    session.scalar.side_effect = [FlowRunStatus.RUNNING.value, None, None]
    repo = FlowRunRepository(session=session)
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
            dispatch_task_id=None,
        )

    assert exc_info.value.operation == "create_flow_step_attempt"
    assert exc_info.value.run_id == run_id
    assert exc_info.value.tenant_id == tenant_id
    assert exc_info.value.flow_id == flow_id
    assert session.scalar.await_count == 3


@pytest.mark.asyncio
async def test_create_raises_runtime_upload_binding_race_payload() -> None:
    session = AsyncMock()
    session.scalar.return_value = SimpleNamespace(id=uuid4())
    session.execute.side_effect = _integrity_error_for_constraint(
        "fk_flow_run_step_input_files_runtime_upload"
    )
    repo = FlowRunRepository(session=session)
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
    repo = FlowRunRepository(session=session)

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
