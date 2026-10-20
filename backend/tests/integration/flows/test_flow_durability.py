"""Durable dispatch, attempt records and outcome-unknown safety."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import sqlalchemy as sa

from eneo.database.tables.flow_tables import FlowRuns, FlowStepAttempts
from eneo.database.tables.job_table import Jobs
from eneo.flows.definition import FlowDefinition, LlmStep, ReviewStep
from eneo.flows.flow_models import (
    FlowRunStatus,
    StepAttemptStatus,
    StepResultStatus,
)
from eneo.flows.flow_run_executor import OUTCOME_UNKNOWN
from eneo.jobs.job_models import Task
from eneo.jobs.task_models import (
    FlowRunDispatchEnvelope,
    FlowRunParams,
    build_dispatch_envelope,
    validate_dispatch_envelope,
)
from tests.integration.flows.conftest import topic_field


def _simple(model_id, *, review: bool = False) -> FlowDefinition:
    steps = [
        LlmStep(
            key="step",
            name="Step",
            prompt="p",
            input="{{form.topic}}",
            model_id=model_id,
        )
    ]
    if review:
        steps.append(ReviewStep(key="check", name="Check"))
    return FlowDefinition(form_fields=[topic_field()], steps=steps)


def test_flow_run_dispatch_envelope_roundtrip():
    params = FlowRunParams(id=uuid4(), flow_id=uuid4(), user_id=uuid4())
    envelope = build_dispatch_envelope(Task.RUN_FLOW, params)
    assert isinstance(envelope, FlowRunDispatchEnvelope)
    parsed = validate_dispatch_envelope(envelope.model_dump(mode="json"))
    assert parsed.task == Task.RUN_FLOW
    assert parsed.params.flow_id == params.flow_id


async def test_create_run_persists_dispatch_envelope(
    db_container, member_space, completion_model_factory, publish_flow, provider
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "durable-model")
        space = await member_space(session, "Durable Space", [model.id])
        flow = await publish_flow(container, space, _simple(model.id))

        run = await container.flow_run_service().create_run(
            flow.id, values={"topic": "q"}, files={}
        )
        job_row = (
            await session.execute(sa.select(Jobs).where(Jobs.id == run.job_id))
        ).scalar_one()
        assert job_row.task == Task.RUN_FLOW.value
        envelope = validate_dispatch_envelope(job_row.dispatch_envelope)
        assert envelope.task == Task.RUN_FLOW
        assert envelope.params.id == run.id
        assert envelope.params.flow_id == flow.id


async def test_idempotency_key_returns_the_existing_run(
    db_container, member_space, completion_model_factory, publish_flow, provider
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "idem-model")
        space = await member_space(session, "Idem Space", [model.id])
        flow = await publish_flow(container, space, _simple(model.id))
        run_service = container.flow_run_service()
        first = await run_service.create_run(
            flow.id, values={"topic": "q"}, files={}, idempotency_key="abc"
        )
        again = await run_service.create_run(
            flow.id, values={"topic": "other"}, files={}, idempotency_key="abc"
        )
        assert again.id == first.id
        _, total = await run_service.list_runs(flow.id)
        assert total == 1


async def test_attempt_numbers_derive_and_close_with_cas(
    db_container, member_space, completion_model_factory, publish_flow, provider
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "attempt-model")
        space = await member_space(session, "Attempt Space", [model.id])
        flow = await publish_flow(container, space, _simple(model.id))
        run = await container.flow_run_service().create_run(
            flow.id, values={"topic": "q"}, files={}
        )
        repo = container.flow_repo()
        step_id = run.steps[0].step_id

        assert await repo.open_attempt(run.id, step_id) == 1
        assert await repo.finish_attempt(
            run.id, step_id, 1, status=StepAttemptStatus.FAILED, error="boom"
        )
        assert await repo.open_attempt(run.id, step_id) == 2
        assert await repo.finish_attempt(
            run.id, step_id, 2, status=StepAttemptStatus.COMPLETED
        )
        # A closed attempt cannot be closed again (reconciler-vs-worker CAS).
        assert not await repo.finish_attempt(
            run.id, step_id, 2, status=StepAttemptStatus.FAILED
        )
        result = await repo.get_step_result(run.id, step_id)
        assert result.current_attempt_no == 2


async def test_unresolved_claimed_step_fails_run_without_repeating_provider_call(
    db_container, member_space, completion_model_factory, publish_flow, provider
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "unknown-model")
        space = await member_space(session, "Unknown Space", [model.id])
        flow = await publish_flow(container, space, _simple(model.id))
        run_service = container.flow_run_service()
        run = await run_service.create_run(flow.id, values={"topic": "q"}, files={})
        repo = container.flow_repo()
        step_id = run.steps[0].step_id

        # A worker claimed the step, opened an attempt and died with the
        # provider outcome unknown.
        assert await repo.claim_step_result(run.id, step_id)
        await repo.open_attempt(run.id, step_id)
        await repo.update_run_status(run.id, FlowRunStatus.RUNNING)

        await run_service.execute_run(run.id)

        finished = await run_service.get_run(run.id)
        assert finished.status == FlowRunStatus.FAILED
        assert finished.error.code == OUTCOME_UNKNOWN
        assert provider.calls == []
        attempt_status = (
            await session.execute(
                sa.select(FlowStepAttempts.status).where(
                    FlowStepAttempts.flow_run_id == run.id
                )
            )
        ).scalar_one()
        assert attempt_status == StepAttemptStatus.OUTCOME_UNKNOWN.value
        assert finished.steps[0].error_code == OUTCOME_UNKNOWN


async def test_stale_running_run_selection_and_terminalization(
    db_container, member_space, completion_model_factory, publish_flow, provider
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "stale-model")
        space = await member_space(session, "Stale Space", [model.id])
        flow = await publish_flow(container, space, _simple(model.id))
        run_service = container.flow_run_service()
        run = await run_service.create_run(flow.id, values={"topic": "q"}, files={})
        repo = container.flow_repo()
        step_id = run.steps[0].step_id

        assert await repo.claim_step_result(run.id, step_id)
        await repo.open_attempt(run.id, step_id)
        await repo.update_run_status(run.id, FlowRunStatus.RUNNING)
        assert await repo.touch_heartbeat(run.id)
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run.id)
            .values(heartbeat_at=datetime.now(UTC) - timedelta(minutes=30))
        )

        stale = await repo.get_stale_running_runs(
            stale_before=datetime.now(UTC) - timedelta(minutes=10)
        )
        assert [r.id for r in stale] == [run.id]

        # The reconciler's transitions (mirrored from reconcile_stale_flow_runs).
        await repo.mark_started_attempts_outcome_unknown(run.id)
        await repo.fail_running_step_results(
            run.id, error_code=OUTCOME_UNKNOWN, error_message="worker lost"
        )
        assert await repo.update_run_status(
            run.id,
            FlowRunStatus.FAILED,
            error={"code": "flow_run_interrupted_outcome_unknown", "message": ""},
            expected_statuses=(FlowRunStatus.RUNNING,),
        )
        # CAS: a slow worker cannot resurrect the reconciled run.
        assert not await repo.update_run_status(
            run.id, FlowRunStatus.COMPLETED, expected_statuses=(FlowRunStatus.RUNNING,)
        )
        assert not await repo.touch_heartbeat(run.id)
        result = await repo.get_step_result(run.id, step_id)
        assert result.status == StepResultStatus.FAILED.value


async def test_awaiting_review_runs_are_not_stale_candidates(
    db_container, member_space, completion_model_factory, publish_flow, provider
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "review-stale-model")
        space = await member_space(session, "Review Stale Space", [model.id])
        flow = await publish_flow(container, space, _simple(model.id, review=True))
        run_service = container.flow_run_service()
        run = await run_service.create_run(flow.id, values={"topic": "q"}, files={})
        await run_service.execute_run(run.id)

        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run.id)
            .values(heartbeat_at=datetime.now(UTC) - timedelta(days=2))
        )
        stale = await container.flow_repo().get_stale_running_runs(
            stale_before=datetime.now(UTC) - timedelta(minutes=10)
        )
        assert stale == []
        assert (
            await run_service.get_run(run.id)
        ).status == FlowRunStatus.AWAITING_REVIEW


async def test_cancel_stops_an_active_run_and_closes_its_checkpoint(
    db_container, member_space, completion_model_factory, publish_flow, provider
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "cancel-model")
        space = await member_space(session, "Cancel Space", [model.id])
        flow = await publish_flow(container, space, _simple(model.id, review=True))
        run_service = container.flow_run_service()
        run = await run_service.create_run(flow.id, values={"topic": "q"}, files={})
        await run_service.execute_run(run.id)

        cancelled = await run_service.cancel_run(run.id, flow_id=flow.id)
        assert cancelled.status == FlowRunStatus.CANCELLED
        assert cancelled.cancelled_at is not None
        assert cancelled.review_checkpoint is None
        assert cancelled.steps[1].status == StepResultStatus.CANCELLED

        # Nothing left to execute: the worker returns without touching it.
        await run_service.execute_run(run.id)
        assert (await run_service.get_run(run.id)).status == FlowRunStatus.CANCELLED
