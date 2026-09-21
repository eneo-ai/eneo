from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.authentication.principal_types import PrincipalType
from eneo.database.database import sessionmanager
from eneo.database.tables.flow_tables import (
    FlowRunAuditOutbox,
    FlowRunReviewCheckpoints,
    FlowRuns,
    FlowStepAttempts,
)
from eneo.flows.domain.flow_run_recovery_policy import (
    FLOW_DISPATCH_MAX_ATTEMPTS,
    FlowRunAbandonmentDeadlineExceeded,
    flow_run_abandonment_deadline,
)
from eneo.flows.domain.review_checkpoint_exceptions import (
    FlowReviewCheckpointCancelledError,
)
from eneo.flows.enums import FlowOutputType, FlowRunReviewCheckpointState, FlowRunStatus
from eneo.flows.flow_review_policy import FlowStepReviewMode
from eneo.flows.flow_run_error import FlowRunAbandonmentFacts
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.principal import FlowPrincipal
from tests.integration.flows.test_flow_run_review_checkpoint_repository import (
    _complete_reviewed_step_result,
    _create_review_checkpoint_scenario,
    _create_service_principal_id,
    _review_checkpoint_repo,
)
from tests.integration.flows.test_flow_terminalization_contract import (
    _flow_run_terminalizer,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def approved_wait(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session, session.begin():
        scenario = await _create_review_checkpoint_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        repo = FlowRunRepository(session=session)
        checkpoint_repo = _review_checkpoint_repo(session=session, run_repo=repo)
        assert await repo.mark_running_if_claimable(
            run_id=scenario.flow_run_id,
            tenant_id=scenario.tenant_id,
            expected_revision=scenario.run.revision,
        )
        await _complete_reviewed_step_result(session=session, scenario=scenario)
        opened = await checkpoint_repo.open_review_checkpoint_for_completed_step(
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
        reviewer = FlowPrincipal(
            principal_type=PrincipalType.SERVICE_KEY,
            principal_service_id=await _create_service_principal_id(
                session=session,
                tenant_id=scenario.tenant_id,
                created_by_user_id=admin_user.id,
            ),
        )
        checkpoint = await checkpoint_repo.approve_review_checkpoint(
            checkpoint_id=opened.checkpoint.id,
            tenant_id=scenario.tenant_id,
            flow_id=scenario.flow_id,
            flow_run_id=scenario.flow_run_id,
            expected_revision=opened.checkpoint.revision,
            principal=reviewer,
        )
        anchor = datetime.now(timezone.utc) - timedelta(days=31)
        await session.execute(
            sa.update(FlowRunReviewCheckpoints)
            .where(
                FlowRunReviewCheckpoints.id == checkpoint.id,
            )
            .values(approved_at=anchor)
        )
        checkpoint = checkpoint.model_copy(update={"approved_at": anchor})
        run = await repo.get(run_id=scenario.flow_run_id, tenant_id=scenario.tenant_id)
    return (
        run,
        checkpoint,
        FlowRunAbandonmentFacts(
            wait="approved_review",
            anchor_at=anchor,
            deadline=flow_run_abandonment_deadline(anchor),
            checkpoint_id=checkpoint.id,
        ),
    )


@pytest.fixture
async def exhausted_wait(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session, session.begin():
        scenario = await _create_review_checkpoint_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        anchor = datetime.now(timezone.utc) - timedelta(days=31)
        await session.execute(
            sa.update(FlowRuns)
            .where(
                FlowRuns.id == scenario.flow_run_id,
            )
            .values(
                dispatch_pending_since=anchor,
                dispatch_attempt_count=FLOW_DISPATCH_MAX_ATTEMPTS,
                dispatched_at=anchor,
                dispatch_exhausted_at=anchor + timedelta(minutes=30),
                dispatch_next_attempt_at=None,
            )
        )
        run = await FlowRunRepository(session=session).get(
            run_id=scenario.flow_run_id,
            tenant_id=scenario.tenant_id,
        )
    return run, FlowRunAbandonmentFacts(
        wait="exhausted_dispatch",
        anchor_at=anchor,
        deadline=flow_run_abandonment_deadline(anchor),
    )


async def test_approved_abandonment_keeps_approval_payload_and_attempt_history(
    approved_wait,
):
    run, approved, facts = approved_wait
    async with sessionmanager.session() as session, session.begin():
        repo = FlowRunRepository(session=session)
        candidates = await repo.list_recovery_candidates(tenant_id=run.tenant_id)
        assert next(row for row in candidates if row.id == run.id).abandonment == facts
        terminalizer = _flow_run_terminalizer(repo)
        result = await terminalizer.terminalize_abandoned_run(
            run_id=run.id,
            tenant_id=run.tenant_id,
            expected_revision=run.revision,
            facts=facts,
        )
        replay = await terminalizer.terminalize_abandoned_run(
            run_id=run.id,
            tenant_id=run.tenant_id,
            expected_revision=run.revision,
            facts=facts,
        )
        assert result.did_transition and not replay.did_transition
        assert result.run.status == FlowRunStatus.FAILED
        assert result.run.error.code == "flow_run_abandoned"
        assert result.run.error.details.abandonment == facts
        assert result.run.error.retryable is False
        assert result.run.input_payload_json == run.input_payload_json
        checkpoint = await session.scalar(
            sa.select(FlowRunReviewCheckpoints).where(
                FlowRunReviewCheckpoints.id == approved.id,
            )
        )
        assert checkpoint.state == FlowRunReviewCheckpointState.CANCELLED.value
        assert checkpoint.approved_at == approved.approved_at
        assert checkpoint.decided_by_user_id == approved.decided_by_user_id
        assert checkpoint.decided_by_service_id == approved.decided_by_service_id
        assert (
            checkpoint.decided_by_principal_type
            == approved.decided_by_principal_type.value
        )
        assert checkpoint.revision == approved.revision + 1
        assert checkpoint.current_payload_json == approved.current_payload_json
        assert checkpoint.original_payload_json == approved.original_payload_json
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(FlowStepAttempts)
                .where(
                    FlowStepAttempts.flow_run_id == run.id,
                )
            )
            == 1
        )
        audits = (
            (
                await session.execute(
                    sa.select(FlowRunAuditOutbox).where(
                        FlowRunAuditOutbox.flow_run_id == run.id,
                        FlowRunAuditOutbox.action.in_(
                            [
                                ActionType.FLOW_RUN_FAILED.value,
                                ActionType.FLOW_RUN_REVIEW_CHECKPOINT_CANCELLED.value,
                            ]
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(audits) == 2
        assert all(
            row.actor_type == ActorType.SYSTEM.value and row.actor_id is None
            for row in audits
        )


@pytest.mark.parametrize(
    ("resume_order", "refusal"),
    [
        ("before_sweep", FlowRunAbandonmentDeadlineExceeded),
        ("after_sweep", FlowReviewCheckpointCancelledError),
        (
            "concurrent",
            (FlowRunAbandonmentDeadlineExceeded, FlowReviewCheckpointCancelledError),
        ),
    ],
)
async def test_overdue_resume_and_two_sweeps_commit_one_terminal_transition(
    approved_wait, admin_user, resume_order, refusal
):
    run, checkpoint, facts = approved_wait
    barrier = asyncio.Barrier(3 if resume_order == "concurrent" else 2)

    async def recover():
        async with sessionmanager.session() as session, session.begin():
            await barrier.wait()
            return await _flow_run_terminalizer(
                FlowRunRepository(session=session)
            ).terminalize_abandoned_run(
                run_id=run.id,
                tenant_id=run.tenant_id,
                expected_revision=run.revision,
                facts=facts,
            )

    async def resume():
        with pytest.raises(refusal):
            async with sessionmanager.session() as session, session.begin():
                if resume_order == "concurrent":
                    await barrier.wait()
                repo = FlowRunRepository(session=session)
                await _review_checkpoint_repo(
                    session=session, run_repo=repo
                ).resume_review_checkpoint(
                    checkpoint_id=checkpoint.id,
                    tenant_id=run.tenant_id,
                    flow_id=run.flow_id,
                    flow_run_id=run.id,
                    expected_revision=checkpoint.revision,
                    resume_idempotency_key="overdue-resume",
                    principal=FlowPrincipal.from_user(admin_user),
                )

    if resume_order == "concurrent":
        first, second, _ = await asyncio.wait_for(
            asyncio.gather(recover(), recover(), resume()), timeout=5
        )
    else:
        if resume_order == "before_sweep":
            await resume()
        first, second = await asyncio.wait_for(
            asyncio.gather(recover(), recover()), timeout=5
        )
        if resume_order == "after_sweep":
            await resume()
    assert sum(result.did_transition for result in (first, second)) == 1
    async with sessionmanager.session() as session, session.begin():
        for action in (
            ActionType.FLOW_RUN_FAILED,
            ActionType.FLOW_RUN_REVIEW_CHECKPOINT_CANCELLED,
        ):
            assert (
                await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(FlowRunAuditOutbox)
                    .where(
                        FlowRunAuditOutbox.flow_run_id == run.id,
                        FlowRunAuditOutbox.action == action.value,
                    )
                )
                == 1
            )


@pytest.mark.parametrize("winner", ["abandonment", "worker_claim", "new_epoch"])
async def test_exhausted_abandonment_rechecks_state_and_anchor_after_lock_wait(
    exhausted_wait, winner
):
    run, facts = exhausted_wait
    waiting_pid = asyncio.get_running_loop().create_future()

    async def contend():
        async with sessionmanager.session() as session, session.begin():
            waiting_pid.set_result(
                await session.scalar(sa.select(sa.func.pg_backend_pid()))
            )
            repo = FlowRunRepository(session=session)
            if winner == "abandonment":
                return await repo.mark_running_if_claimable(
                    run_id=run.id,
                    tenant_id=run.tenant_id,
                    expected_revision=run.revision,
                )
            result = await _flow_run_terminalizer(repo).terminalize_abandoned_run(
                run_id=run.id,
                tenant_id=run.tenant_id,
                expected_revision=run.revision,
                facts=facts,
            )
            return result.did_transition

    contender = None
    try:
        async with sessionmanager.session() as writer, writer.begin():
            await writer.scalar(
                sa.select(FlowRuns.id).where(FlowRuns.id == run.id).with_for_update()
            )
            repo = FlowRunRepository(session=writer)
            if winner == "abandonment":
                result = await _flow_run_terminalizer(repo).terminalize_abandoned_run(
                    run_id=run.id,
                    tenant_id=run.tenant_id,
                    expected_revision=run.revision,
                    facts=facts,
                )
                assert result.did_transition
                assert result.run.error.details.abandonment == facts
            elif winner == "worker_claim":
                assert await repo.mark_running_if_claimable(
                    run_id=run.id,
                    tenant_id=run.tenant_id,
                    expected_revision=run.revision,
                )
            else:
                # A subsequent exhausted epoch can have the same status and run revision.
                await writer.execute(
                    sa.update(FlowRuns)
                    .where(FlowRuns.id == run.id)
                    .values(
                        dispatch_pending_since=datetime.now(timezone.utc),
                    )
                )
            contender = asyncio.create_task(contend())
            async with asyncio.timeout(5):
                pid = await waiting_pid
                async with sessionmanager.session() as observer, observer.begin():
                    while not await observer.scalar(
                        sa.select(
                            sa.func.cardinality(sa.func.pg_blocking_pids(pid)) > 0
                        )
                    ):
                        assert not contender.done()
                        await asyncio.sleep(0.01)
        assert await asyncio.wait_for(contender, timeout=5) is False
        async with sessionmanager.session() as session, session.begin():
            current = await FlowRunRepository(session=session).get(
                run_id=run.id, tenant_id=run.tenant_id
            )
            assert (
                current.status
                == {
                    "abandonment": FlowRunStatus.FAILED,
                    "worker_claim": FlowRunStatus.RUNNING,
                    "new_epoch": FlowRunStatus.QUEUED,
                }[winner]
            )
            assert current.input_payload_json == run.input_payload_json
            assert await session.scalar(
                sa.select(sa.func.count())
                .select_from(FlowRunAuditOutbox)
                .where(
                    FlowRunAuditOutbox.flow_run_id == run.id,
                    FlowRunAuditOutbox.action == ActionType.FLOW_RUN_FAILED.value,
                )
            ) == (1 if winner == "abandonment" else 0)
    finally:
        if contender is not None:
            if not contender.done():
                contender.cancel()
            await asyncio.gather(contender, return_exceptions=True)
