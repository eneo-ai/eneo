"""Deleting a flow serializes with run admission on the flow row lock, and the
retired-flow drain cancels the runs a deleted flow still has in flight."""

from __future__ import annotations

import asyncio
import wave
from collections.abc import Awaitable
from datetime import datetime, timedelta, timezone
from io import BytesIO
from time import monotonic
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from dependency_injector import providers

from eneo.data_retention.infrastructure.data_retention_service import (
    DataRetentionService,
)
from eneo.database.database import sessionmanager
from eneo.database.tables.flow_tables import (
    FlowRunAuditOutbox,
    FlowRunReviewCheckpoints,
    FlowRuns,
    FlowRuntimeUploadedFiles,
    Flows,
)
from eneo.flows.application.flow_run_terminalization import FlowRunTerminalizer
from eneo.flows.domain.flow import FlowRun, FlowRunStatus
from eneo.flows.domain.flow_run_retention_policy import FlowRunRetentionMode
from eneo.flows.enums import (
    TERMINAL_FLOW_RUN_STATUSES,
    FlowOutputType,
    FlowRunLifecycleSource,
    FlowRunReviewCheckpointState,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_review_policy import FlowStepReviewMode
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.principal import FlowPrincipal
from eneo.flows.runtime import tasks as flow_runtime_tasks
from eneo.main.container.container import Container
from eneo.main.exceptions import NotFoundException
from tests.integration.flows.test_flow_live_transcription_session import (
    _published_flow,
)
from tests.integration.flows.test_flow_run_publication_locking import (
    _create_published_flow_with_two_versions,
)
from tests.integration.flows.test_flow_run_review_checkpoint_repository import (
    _complete_reviewed_step_result,
    _create_review_checkpoint_scenario,
    _review_checkpoint_repo,
)
from tests.integration.flows.test_flow_terminalization_contract import (
    _create_running_run,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _drain(**kwargs: int) -> dict[str, int | str]:
    return await flow_runtime_tasks._drain_retired_flow_runs(**kwargs)


async def _backend_pid(session) -> int:
    pid = await session.scalar(sa.text("SELECT pg_backend_pid()"))
    assert isinstance(pid, int)
    return pid


async def _until_blocked_by_or_done(
    *, holder_pid: int, task: asyncio.Task[Any], timeout_seconds: float = 10
) -> None:
    """Return once some backend waits on the holder's locks, or the task ended."""
    deadline = monotonic() + timeout_seconds
    async with sessionmanager.session() as observer, observer.begin():
        while monotonic() < deadline:
            if task.done():
                return
            blocked = await observer.scalar(
                sa.text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE :holder = ANY(pg_blocking_pids(pid))"
                ),
                {"holder": holder_pid},
            )
            if blocked:
                return
            await asyncio.sleep(0.01)
    pytest.fail("The competing writer neither waited on the flow lock nor ended.")


async def _run(run_id: UUID, tenant_id: UUID) -> FlowRun:
    async with sessionmanager.session() as session, session.begin():
        return await FlowRunRepository(session).get(run_id=run_id, tenant_id=tenant_id)


async def _retire(flow_id: UUID, tenant_id: UUID) -> None:
    async with sessionmanager.session() as session, session.begin():
        await FlowRepository(session).delete(flow_id, tenant_id)


async def _terminal_outbox_rows(run_id: UUID) -> list[dict[str, Any]]:
    async with sessionmanager.session() as session, session.begin():
        rows = await session.execute(
            sa.select(
                FlowRunAuditOutbox.action,
                FlowRunAuditOutbox.source,
                FlowRunAuditOutbox.error_code,
                FlowRunAuditOutbox.actor_type,
                FlowRunAuditOutbox.actor_id,
                FlowRunAuditOutbox.actor_snapshot,
            ).where(
                FlowRunAuditOutbox.flow_run_id == run_id,
                FlowRunAuditOutbox.review_checkpoint_id.is_(None),
            )
        )
        return [dict(row) for row in rows.mappings()]


async def _assert_cancelled_because_flow_deleted(run_id: UUID, tenant_id: UUID):
    run = await _run(run_id, tenant_id)
    assert run.status is FlowRunStatus.CANCELLED
    assert run.error is not None
    assert run.error.code is FlowApiErrorCode.FLOW_DELETED
    assert run.error.source is FlowRunLifecycleSource.FLOW_DELETED
    [outbox] = await _terminal_outbox_rows(run_id)
    assert outbox == {
        "action": "flow_run_cancelled",
        "source": FlowRunLifecycleSource.FLOW_DELETED.value,
        "error_code": FlowApiErrorCode.FLOW_DELETED.value,
        "actor_type": "system",
        "actor_id": None,
        "actor_snapshot": {"type": "system", "via": "flow_deleted"},
    }


def _run_container(session, admin_user, test_tenant) -> Container:
    return Container(
        session=providers.Object(session),
        user=providers.Object(admin_user),
        tenant=providers.Object(test_tenant),
    )


async def _published_flow_id(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> UUID:
    async with db_container() as setup_container:
        flow_id = await _create_published_flow_with_two_versions(
            container=setup_container,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        await setup_container.session().commit()
    return flow_id


async def test_delete_committed_first_refuses_run_creation_without_a_run_row(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    test_tenant,
    object_content_runtime_ready,
) -> None:
    flow_id = await _published_flow_id(
        db_container,
        completion_model_factory,
        space_factory,
        assistant_factory,
        admin_user,
    )
    async with (
        sessionmanager.session() as delete_session,
        sessionmanager.session() as run_session,
    ):
        await delete_session.begin()
        delete_pid = await _backend_pid(delete_session)
        await FlowRepository(delete_session).delete(flow_id, admin_user.tenant_id)
        await run_session.begin()
        creation = asyncio.create_task(
            _run_container(run_session, admin_user, test_tenant)
            .flow_run_service()
            .create_run(flow_id=flow_id, input_payload_json={"question": "race"})
        )
        try:
            await _until_blocked_by_or_done(holder_pid=delete_pid, task=creation)
            assert not creation.done()
            await delete_session.commit()
            with pytest.raises(NotFoundException):
                await asyncio.wait_for(creation, timeout=5)
        finally:
            if not creation.done():
                creation.cancel()
                await asyncio.gather(creation, return_exceptions=True)
            await run_session.rollback()
            if delete_session.in_transaction():
                await delete_session.rollback()

    async with sessionmanager.session() as session, session.begin():
        run_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRuns)
            .where(FlowRuns.flow_id == flow_id)
        )
    assert run_count == 0


async def test_run_created_first_is_drained_after_the_delete_commits(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    test_tenant,
    object_content_runtime_ready,
) -> None:
    flow_id = await _published_flow_id(
        db_container,
        completion_model_factory,
        space_factory,
        assistant_factory,
        admin_user,
    )
    async with (
        sessionmanager.session() as run_session,
        sessionmanager.session() as delete_session,
    ):
        await run_session.begin()
        run_pid = await _backend_pid(run_session)
        created = await (
            _run_container(run_session, admin_user, test_tenant)
            .flow_run_service()
            .create_run(flow_id=flow_id, input_payload_json={"question": "race"})
        )
        await delete_session.begin()
        deletion = asyncio.create_task(
            FlowRepository(delete_session).delete(flow_id, admin_user.tenant_id)
        )
        try:
            await _until_blocked_by_or_done(holder_pid=run_pid, task=deletion)
            assert not deletion.done()
            await run_session.commit()
            await asyncio.wait_for(deletion, timeout=5)
            await delete_session.commit()
        finally:
            if not deletion.done():
                deletion.cancel()
                await asyncio.gather(deletion, return_exceptions=True)
            for session in (run_session, delete_session):
                if session.in_transaction():
                    await session.rollback()

    run_id = created.run.id
    assert (await _run(run_id, admin_user.tenant_id)).status is FlowRunStatus.QUEUED
    result = await _drain()
    assert result["status"] == "ok"
    await _assert_cancelled_because_flow_deleted(run_id, admin_user.tenant_id)


def _wav() -> bytes:
    payload = BytesIO()
    with wave.open(payload, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 16000)
    return payload.getvalue()


async def test_delete_committed_first_refuses_the_runtime_upload_bind(
    client, flow_process_auth_headers, db_container
) -> None:
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(client, headers, db_container)
    flow_id = UUID(flow.flow_id)
    async with sessionmanager.session() as session, session.begin():
        tenant_id = await session.scalar(
            sa.select(Flows.tenant_id).where(Flows.id == flow_id)
        )
    assert isinstance(tenant_id, UUID)

    async with sessionmanager.session() as delete_session:
        await delete_session.begin()
        delete_pid = await _backend_pid(delete_session)
        await FlowRepository(delete_session).delete(flow_id, tenant_id)
        upload = asyncio.create_task(
            client.post(
                f"/api/v1/flows/{flow.flow_id}/steps/{flow.step_id}/runtime-files/",
                headers=headers,
                files={"upload_file": ("race.wav", _wav(), "audio/wav")},
            )
        )
        try:
            await _until_blocked_by_or_done(holder_pid=delete_pid, task=upload)
            await delete_session.commit()
            response = await asyncio.wait_for(upload, timeout=10)
        finally:
            if not upload.done():
                upload.cancel()
                await asyncio.gather(upload, return_exceptions=True)
            if delete_session.in_transaction():
                await delete_session.rollback()

    async with sessionmanager.session() as session, session.begin():
        bound = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRuntimeUploadedFiles)
            .where(FlowRuntimeUploadedFiles.flow_id == flow_id)
        )
    assert bound == 0
    assert response.status_code == 404, response.text


async def _queued_run(session, admin_user, factories) -> tuple[UUID, UUID]:
    running, flow, run_repo = await _create_running_run(
        session=session, admin_user=admin_user, start_attempt=False, **factories
    )
    queued = await run_repo.create(
        flow_id=flow.id,
        flow_version=1,
        principal_user_id=admin_user.id,
        tenant_id=admin_user.tenant_id,
        input_payload_json={"question": "queued"},
        preseed_steps=[
            {
                "step_id": step.id,
                "assistant_id": step.assistant_id,
                "step_order": step.step_order,
            }
            for step in flow.steps
        ],
    )
    # Only the queued run stays non-terminal on this flow.
    await FlowRunTerminalizer(
        run_repo,
        run_repo.audit_outbox_repo,
        _review_checkpoint_repo(session=session, run_repo=run_repo),
    ).terminalize_run(
        run_id=running.id,
        tenant_id=admin_user.tenant_id,
        target_status=FlowRunStatus.FAILED,
        source=FlowRunLifecycleSource.EXECUTOR_FAILED,
        error=FlowRunError(
            code=FlowApiErrorCode.STEP_EXECUTION_FAILED, message="seeded"
        ),
    )
    return flow.id, queued.id


async def _running_run(session, admin_user, factories) -> tuple[UUID, UUID]:
    run, flow, _ = await _create_running_run(
        session=session, admin_user=admin_user, **factories
    )
    return flow.id, run.id


async def _awaiting_review_run(session, admin_user, factories) -> tuple[UUID, UUID]:
    scenario = await _create_review_checkpoint_scenario(
        session=session, admin_user=admin_user, **factories
    )
    run_repo = FlowRunRepository(session=session)
    await run_repo.mark_running_if_claimable(
        run_id=scenario.flow_run_id,
        tenant_id=scenario.tenant_id,
        expected_revision=scenario.run.revision,
    )
    await _complete_reviewed_step_result(session=session, scenario=scenario)
    await _review_checkpoint_repo(
        session=session, run_repo=run_repo
    ).open_review_checkpoint_for_completed_step(
        tenant_id=scenario.tenant_id,
        flow_id=scenario.flow_id,
        flow_run_id=scenario.flow_run_id,
        step_id=scenario.step_ids[0],
        step_order=1,
        attempt_no=1,
        requester_principal=FlowPrincipal.from_user(admin_user),
        next_step_ids=(scenario.step_ids[1],),
        review_mode=FlowStepReviewMode.VIEW,
        output_type=FlowOutputType.JSON,
    )
    return scenario.flow_id, scenario.flow_run_id


@pytest.fixture
def factories(completion_model_factory, space_factory, assistant_factory):
    return {
        "completion_model_factory": completion_model_factory,
        "space_factory": space_factory,
        "assistant_factory": assistant_factory,
    }


async def _seed(seeder, admin_user, factories) -> tuple[UUID, UUID]:
    async with sessionmanager.session() as session, session.begin():
        return await seeder(session, admin_user, factories)


@pytest.mark.parametrize(
    "seeder",
    [_queued_run, _running_run, _awaiting_review_run],
    ids=["queued", "running", "awaiting_review"],
)
async def test_drain_cancels_a_deleted_flows_run_in_each_non_terminal_state(
    setup_database, admin_user, factories, seeder
) -> None:
    flow_id, run_id = await _seed(seeder, admin_user, factories)
    await _retire(flow_id, admin_user.tenant_id)

    await _drain()

    await _assert_cancelled_because_flow_deleted(run_id, admin_user.tenant_id)
    async with sessionmanager.session() as session, session.begin():
        checkpoints = [
            tuple(row)
            for row in await session.execute(
                sa.select(
                    FlowRunReviewCheckpoints.state,
                    FlowRunReviewCheckpoints.decided_by_principal_type,
                    FlowRunReviewCheckpoints.decided_by_user_id,
                    FlowRunReviewCheckpoints.decided_by_service_id,
                ).where(FlowRunReviewCheckpoints.flow_run_id == run_id)
            )
        ]
        checkpoint_outbox = [
            tuple(row)
            for row in await session.execute(
                sa.select(
                    FlowRunAuditOutbox.action,
                    FlowRunAuditOutbox.actor_type,
                    FlowRunAuditOutbox.actor_id,
                )
                .where(
                    FlowRunAuditOutbox.flow_run_id == run_id,
                    FlowRunAuditOutbox.review_checkpoint_id.is_not(None),
                )
                .order_by(FlowRunAuditOutbox.checkpoint_revision)
            )
        ]
    if seeder is _awaiting_review_run:
        # The system cancelled the review: nobody is recorded as its decider.
        assert checkpoints == [
            (FlowRunReviewCheckpointState.CANCELLED.value, None, None, None)
        ]
        assert checkpoint_outbox == [
            ("flow_run_review_checkpoint_opened", "user", admin_user.id),
            ("flow_run_review_checkpoint_cancelled", "system", None),
        ]
    else:
        assert checkpoints == []


async def test_drain_leaves_runs_of_live_flows_alone(
    setup_database, admin_user, factories
) -> None:
    _flow_id, run_id = await _seed(_running_run, admin_user, factories)

    await _drain()

    assert (await _run(run_id, admin_user.tenant_id)).status is FlowRunStatus.RUNNING


async def test_concurrent_sweeps_and_a_user_cancel_make_one_transition(
    setup_database, admin_user, factories
) -> None:
    flow_id, run_id = await _seed(_running_run, admin_user, factories)
    await _retire(flow_id, admin_user.tenant_id)

    async def user_cancel() -> None:
        async with sessionmanager.session() as session, session.begin():
            run_repo = FlowRunRepository(session)
            await FlowRunTerminalizer(
                run_repo,
                run_repo.audit_outbox_repo,
                _review_checkpoint_repo(session=session, run_repo=run_repo),
            ).terminalize_run(
                run_id=run_id,
                tenant_id=admin_user.tenant_id,
                target_status=FlowRunStatus.CANCELLED,
                source=FlowRunLifecycleSource.USER_CANCEL,
                error=FlowRunError.from_source(
                    FlowRunLifecycleSource.USER_CANCEL,
                    code=FlowApiErrorCode.RUN_USER_CANCELLED,
                    message="cancelled in test",
                ),
            )

    racers: list[Awaitable[object]] = [_drain(), _drain(), user_cancel()]
    await asyncio.gather(*racers)

    run = await _run(run_id, admin_user.tenant_id)
    assert run.status is FlowRunStatus.CANCELLED
    assert len(await _terminal_outbox_rows(run_id)) == 1


async def test_drain_is_bounded_per_sweep_and_finishes_over_later_sweeps(
    setup_database, admin_user, factories
) -> None:
    await _drain(limit=1000)  # older runs of other tests' deleted flows go first
    async with sessionmanager.session() as session, session.begin():
        run, flow, run_repo = await _create_running_run(
            session=session, admin_user=admin_user, start_attempt=False, **factories
        )
        extra = [
            await run_repo.create(
                flow_id=flow.id,
                flow_version=1,
                principal_user_id=admin_user.id,
                tenant_id=admin_user.tenant_id,
                input_payload_json={"question": f"queued {index}"},
                preseed_steps=[],
            )
            for index in range(2)
        ]
    run_ids = [run.id, *(queued.id for queued in extra)]
    await _retire(flow.id, admin_user.tenant_id)

    async def open_runs() -> int:
        statuses = [(await _run(i, admin_user.tenant_id)).status for i in run_ids]
        return sum(status not in TERMINAL_FLOW_RUN_STATUSES for status in statuses)

    await _drain(limit=2)
    assert await open_runs() == 1
    await _drain(limit=2)
    assert await open_runs() == 0
    for run_id in run_ids:
        await _assert_cancelled_because_flow_deleted(run_id, admin_user.tenant_id)


async def test_a_run_that_fails_to_cancel_does_not_hold_up_the_others(
    setup_database, admin_user, factories, monkeypatch
) -> None:
    async with sessionmanager.session() as session, session.begin():
        poison, flow, run_repo = await _create_running_run(
            session=session, admin_user=admin_user, start_attempt=False, **factories
        )
        later = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"question": "queued later"},
            preseed_steps=[],
        )
    await _retire(flow.id, admin_user.tenant_id)
    original = FlowRunTerminalizer.terminalize_run

    async def fail_for_poison(self, **kwargs: Any):
        if kwargs["run_id"] == poison.id:
            raise RuntimeError("terminalization failed")
        return await original(self, **kwargs)

    monkeypatch.setattr(FlowRunTerminalizer, "terminalize_run", fail_for_poison)

    with pytest.raises(RuntimeError, match="could not cancel 1 run"):
        await _drain()

    await _assert_cancelled_because_flow_deleted(later.id, admin_user.tenant_id)
    assert (await _run(poison.id, admin_user.tenant_id)).status is FlowRunStatus.RUNNING


async def test_the_history_purge_selects_a_drained_run_once_it_is_due(
    setup_database, admin_user, factories
) -> None:
    # The flow's only run, so the dry run's count is this run.
    flow_id, run_id = await _seed(_running_run, admin_user, factories)
    async with sessionmanager.session() as session, session.begin():
        await session.execute(
            sa.update(Flows)
            .where(Flows.id == flow_id)
            .values(
                flow_run_history_retention_mode=FlowRunRetentionMode.PRESERVE.value,
                flow_run_history_retention_days=1,
            )
        )
    await _retire(flow_id, admin_user.tenant_id)

    async def selected() -> bool:
        await flow_runtime_tasks._deliver_flow_audit_outbox()
        async with sessionmanager.session() as session, session.begin():
            result = await DataRetentionService(
                session
            ).purge_due_flow_run_history_for_tenant(
                tenant_id=admin_user.tenant_id,
                now=datetime.now(timezone.utc) + timedelta(days=30),
                limit=500,
                dry_run=True,
                flow_id=flow_id,
            )
        return result.candidate_count == 1

    assert not await selected()
    await _drain()
    await _assert_cancelled_because_flow_deleted(run_id, admin_user.tenant_id)
    assert await selected()
