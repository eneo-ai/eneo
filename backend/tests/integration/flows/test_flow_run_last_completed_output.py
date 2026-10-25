"""The output a completed run returns: the highest-order completed step's, read
as one payload of one run, whatever else the run's other steps hold."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.flow_tables import FlowRuns, FlowStepResults
from eneo.flows import FlowRepository, FlowVersionRepository
from eneo.flows.domain.flow import FlowStepResultStatus
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from tests.flow_snapshot_fixtures import assistant_snapshot
from tests.integration.flows.test_flow_run_repository import (
    _build_flow,  # pyright: ignore[reportPrivateUsage]
)

COMPLETED = FlowStepResultStatus.COMPLETED
CANCELLED = FlowStepResultStatus.CANCELLED
FAILED = FlowStepResultStatus.FAILED
PENDING = FlowStepResultStatus.PENDING


async def _run_with_steps(
    session,
    *,
    flow_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    steps: list[tuple[int, FlowStepResultStatus, str | None]],
) -> UUID:
    """A run whose step results are inserted in the given order, which need not
    be step order."""
    run_row = FlowRuns(
        flow_id=flow_id,
        flow_version=1,
        principal_type="user",
        principal_user_id=user_id,
        tenant_id=tenant_id,
        status="queued",
        input_payload_json={"question": "What happened?"},
    )
    session.add(run_row)
    await session.flush()
    for step_order, status, text in steps:
        session.add(
            FlowStepResults(
                flow_run_id=run_row.id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                step_id=uuid4(),
                step_order=step_order,
                status=status.value,
                input_payload_json={"text": f"input {step_order}"},
                effective_prompt=f"prompt {step_order}",
                output_payload_json=None if text is None else {"text": text},
            )
        )
        await session.flush()
    return run_row.id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_last_completed_output_is_the_highest_completed_step_of_the_run(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Final output space", [model.id])
        assistant = await assistant_factory(
            session, "Final output assistant", model.id, space_id=space.id
        )
        flow = await FlowRepository(session=session).create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        await FlowVersionRepository(session=session).create(
            flow_id=flow.id,
            version=1,
            definition_json={
                "steps": [
                    {
                        "step_id": str(flow.steps[0].id),
                        "assistant_id": str(assistant.id),
                        "assistant_snapshot": assistant_snapshot(assistant.id),
                        "step_order": 1,
                    }
                ]
            },
            tenant_id=admin_user.tenant_id,
        )
        tenant_id = admin_user.tenant_id

        async def run_with(*steps: tuple[int, FlowStepResultStatus, str | None]):
            return await _run_with_steps(
                session,
                flow_id=flow.id,
                tenant_id=tenant_id,
                user_id=admin_user.id,
                steps=list(steps),
            )

        repo = FlowRunRepository(session=session)

        async def last_output(run_id: UUID, *, tenant: UUID = tenant_id):
            return await repo.read_last_completed_output_payload(
                run_id=run_id, tenant_id=tenant
            )

        # Inserted out of step order: the highest completed step wins.
        out_of_order = await run_with(
            (3, COMPLETED, "third"), (1, COMPLETED, "first"), (2, COMPLETED, "second")
        )
        # A later cancelled, failed or pending step is not the run's output.
        later_not_completed = await run_with(
            (1, COMPLETED, "first"),
            (2, COMPLETED, "second"),
            (3, CANCELLED, "cancelled"),
            (4, FAILED, "failed"),
            (5, PENDING, None),
        )
        none_completed = await run_with((1, PENDING, None), (2, CANCELLED, "x"))
        no_steps = await run_with()
        completed_without_output = await run_with(
            (1, COMPLETED, "first"), (2, COMPLETED, None)
        )
        other_run = await run_with((1, COMPLETED, "other run"))

        assert await last_output(out_of_order) == {"text": "third"}
        assert await last_output(later_not_completed) == {"text": "second"}
        assert await last_output(none_completed) is None
        assert await last_output(no_steps) is None
        assert await last_output(completed_without_output) is None
        assert await last_output(other_run) == {"text": "other run"}
        # Another tenant's id never reads this tenant's run.
        assert await last_output(out_of_order, tenant=uuid4()) is None

        # The (flow_run_id, step_order) index serves it backwards, without a sort.
        await session.execute(sa.text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            (
                await session.execute(
                    sa.text(
                        "EXPLAIN SELECT output_payload_json FROM flow_step_results"
                        " WHERE flow_run_id = :run_id AND tenant_id = :tenant_id"
                        " AND status = 'completed'"
                        " ORDER BY step_order DESC LIMIT 1"
                    ),
                    {"run_id": later_not_completed, "tenant_id": tenant_id},
                )
            ).scalars()
        )
        assert "Index Scan Backward using ix_flow_step_results_run_step_order" in plan
        assert "Sort" not in plan
