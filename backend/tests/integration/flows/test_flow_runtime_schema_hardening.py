from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from eneo.database.tables.flow_tables import (
    FlowRuns,
    Flows,
    FlowStepAttempts,
    FlowStepResults,
    FlowSteps,
    FlowVersions,
)
from eneo.flows.domain.flow import (
    FlowRunStatus,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
)


async def _runtime_parent_rows(
    *,
    session,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    model = await completion_model_factory(
        session,
        f"flow-runtime-schema-hardening-model-{uuid4()}",
    )
    space = await space_factory(
        session,
        f"Flow runtime schema hardening {uuid4()}",
        [model.id],
    )
    assistant = await assistant_factory(
        session,
        f"Flow runtime schema hardening assistant {uuid4()}",
        model.id,
        space_id=space.id,
    )
    flow = Flows(
        name=f"Flow runtime schema hardening {uuid4()}",
        description=None,
        tenant_id=admin_user.tenant_id,
        space_id=space.id,
        created_by_user_id=admin_user.id,
        owner_user_id=admin_user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=30,
    )
    session.add(flow)
    await session.flush()

    session.add(
        FlowVersions(
            flow_id=flow.id,
            version=1,
            tenant_id=admin_user.tenant_id,
            definition_checksum="pg12-schema-hardening",
            definition_json={
                "schema_version": 1,
                "flow_id": str(flow.id),
                "steps": [],
            },
        )
    )
    await session.flush()

    run = FlowRuns(
        flow_id=flow.id,
        flow_version=1,
        principal_type="user",
        principal_user_id=admin_user.id,
        principal_service_id=None,
        runtime_service_permission=None,
        tenant_id=admin_user.tenant_id,
        trace_id=uuid4(),
        status=FlowRunStatus.QUEUED.value,
        input_payload_json={},
    )
    session.add(run)
    await session.flush()
    return flow, run, assistant


async def _assert_integrity_error(
    session,
    row: object,
    *,
    constraint_name: str,
) -> None:
    with pytest.raises(IntegrityError) as exc_info:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    assert constraint_name in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("step_order", [0, -1])
async def test_flow_steps_reject_non_positive_step_order(
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
    step_order: int,
) -> None:
    async with db_container() as container:
        session = container.session()
        flow, _, assistant = await _runtime_parent_rows(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )

        await _assert_integrity_error(
            session,
            FlowSteps(
                flow_id=flow.id,
                tenant_id=admin_user.tenant_id,
                assistant_id=assistant.id,
                step_order=step_order,
            ),
            constraint_name="ck_flow_steps_step_order_positive",
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("step_order", 0),
        ("step_order", -1),
        ("current_attempt_no", 0),
        ("current_attempt_no", -1),
    ],
)
async def test_flow_step_results_reject_non_positive_ordinals(
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
    field: str,
    value: int,
) -> None:
    async with db_container() as container:
        session = container.session()
        flow, run, assistant = await _runtime_parent_rows(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        await _assert_integrity_error(
            session,
            FlowStepResults(
                flow_run_id=run.id,
                flow_id=flow.id,
                tenant_id=admin_user.tenant_id,
                step_id=uuid4(),
                step_order=value if field == "step_order" else 1,
                assistant_id=assistant.id,
                current_attempt_no=value if field == "current_attempt_no" else 1,
                status=FlowStepResultStatus.PENDING.value,
            ),
            constraint_name=(
                "ck_flow_step_results_step_order_positive"
                if field == "step_order"
                else "ck_flow_step_results_current_attempt_no_positive"
            ),
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("step_order", 0),
        ("step_order", -1),
        ("attempt_no", 0),
        ("attempt_no", -1),
    ],
)
async def test_flow_step_attempts_reject_non_positive_ordinals(
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
    field: str,
    value: int,
) -> None:
    async with db_container() as container:
        session = container.session()
        flow, run, _ = await _runtime_parent_rows(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        await _assert_integrity_error(
            session,
            FlowStepAttempts(
                flow_run_id=run.id,
                flow_id=flow.id,
                tenant_id=admin_user.tenant_id,
                step_id=uuid4(),
                step_order=value if field == "step_order" else 1,
                attempt_no=value if field == "attempt_no" else 1,
                status=FlowStepAttemptStatus.STARTED.value,
                started_at=datetime.now(timezone.utc),
            ),
            constraint_name=(
                "ck_flow_step_attempts_step_order_positive"
                if field == "step_order"
                else "ck_flow_step_attempts_attempt_no_positive"
            ),
        )
