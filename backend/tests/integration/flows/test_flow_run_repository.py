from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from intric.database.tables.flow_tables import FlowRuns, FlowStepAttempts, FlowStepResults
from intric.flows import Flow, FlowFactory, FlowRepository, FlowStep, FlowVersionRepository
from intric.flows.flow import FlowRunStatus, FlowStepAttemptStatus, FlowStepResultStatus
from intric.flows.flow_run_repo import FlowRunRepository


def _build_flow(
    *,
    tenant_id: UUID,
    space_id: UUID,
    user_id: UUID,
    assistant_id: UUID,
) -> Flow:
    return Flow(
        id=None,
        tenant_id=tenant_id,
        space_id=space_id,
        name="Run creation flow",
        description="Flow used for run repository tests.",
        created_by_user_id=user_id,
        owner_user_id=user_id,
        published_version=None,
        metadata_json=None,
        data_retention_days=30,
        created_at=None,
        updated_at=None,
        steps=[
            FlowStep(
                id=None,
                flow_id=uuid4(),
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                step_order=1,
                user_description="Step one",
                input_source="flow_input",
                input_type="text",
                input_contract=None,
                output_mode="pass_through",
                output_type="json",
                output_contract={"type": "object"},
                input_bindings={"question": "{{flow.input.question}}"},
                output_classification_override=None,
                mcp_policy="inherit",
                input_config=None,
                output_config=None,
            ),
            FlowStep(
                id=None,
                flow_id=uuid4(),
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                step_order=2,
                user_description="Step two",
                input_source="previous_step",
                input_type="json",
                input_contract=None,
                output_mode="pass_through",
                output_type="json",
                output_contract={"type": "object"},
                input_bindings={"summary": "{{step_1.output.summary}}"},
                output_classification_override=None,
                mcp_policy="inherit",
                input_config=None,
                output_config=None,
            ),
        ],
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_run_preseeds_pending_step_results(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows run-repo space", [model.id])
        assistant = await assistant_factory(
            session,
            "Flow Run Assistant",
            model.id,
            space_id=space.id,
        )

        flow_repo = FlowRepository(session=session, factory=FlowFactory())
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        flow = flow.model_copy(update={"published_version": 1})
        flow = await flow_repo.update(flow=flow, tenant_id=admin_user.tenant_id)
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_checksum="checksum-run-repo",
            definition_json={
                "steps": [
                    {
                        "step_id": str(flow.steps[0].id),
                        "assistant_id": str(flow.steps[0].assistant_id),
                        "step_order": 1,
                    },
                    {
                        "step_id": str(flow.steps[1].id),
                        "assistant_id": str(flow.steps[1].assistant_id),
                        "step_order": 2,
                    },
                ]
            },
            tenant_id=admin_user.tenant_id,
        )

        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"question": "What happened?"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                },
                {
                    "step_id": flow.steps[1].id,
                    "assistant_id": flow.steps[1].assistant_id,
                    "step_order": 2,
                },
            ],
        )

        assert run.flow_id == flow.id
        assert run.status == "queued"

        rows = (
            await session.execute(
                sa.select(FlowStepResults)
                .where(FlowStepResults.flow_run_id == run.id)
                .order_by(FlowStepResults.step_order.asc())
            )
        ).scalars().all()

        assert len(rows) == 2
        assert rows[0].step_order == 1
        assert rows[1].step_order == 2
        assert rows[0].status == FlowStepResultStatus.PENDING.value
        assert rows[1].status == FlowStepResultStatus.PENDING.value


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_runs_filters_by_flow_id(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows list-run space", [model.id])
        assistant = await assistant_factory(
            session,
            "Flow List Assistant",
            model.id,
            space_id=space.id,
        )

        flow_repo = FlowRepository(session=session, factory=FlowFactory())
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())

        first_flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        second_flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ).model_copy(update={"name": "Second flow"}),
            tenant_id=admin_user.tenant_id,
        )

        await version_repo.create(
            flow_id=first_flow.id,
            version=1,
            definition_checksum="checksum-list-1",
            definition_json={
                "steps": [
                    {
                        "step_id": str(first_flow.steps[0].id),
                        "assistant_id": str(first_flow.steps[0].assistant_id),
                        "step_order": 1,
                    }
                ]
            },
            tenant_id=admin_user.tenant_id,
        )
        await version_repo.create(
            flow_id=second_flow.id,
            version=1,
            definition_checksum="checksum-list-2",
            definition_json={
                "steps": [
                    {
                        "step_id": str(second_flow.steps[0].id),
                        "assistant_id": str(second_flow.steps[0].assistant_id),
                        "step_order": 1,
                    }
                ]
            },
            tenant_id=admin_user.tenant_id,
        )

        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        await run_repo.create(
            flow_id=first_flow.id,
            flow_version=1,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "one"},
            preseed_steps=[
                {
                    "step_id": first_flow.steps[0].id,
                    "assistant_id": first_flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )
        await run_repo.create(
            flow_id=second_flow.id,
            flow_version=1,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "two"},
            preseed_steps=[
                {
                    "step_id": second_flow.steps[0].id,
                    "assistant_id": second_flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )

        first_flow_runs = await run_repo.list_runs(
            tenant_id=admin_user.tenant_id,
            flow_id=first_flow.id,
        )

    assert len(first_flow_runs) == 1
    assert first_flow_runs[0].flow_id == first_flow.id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_count_active_runs_counts_only_queued_and_running_statuses(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows active-count space", [model.id])
        assistant = await assistant_factory(
            session,
            "Flow active-count assistant",
            model.id,
            space_id=space.id,
        )

        flow_repo = FlowRepository(session=session, factory=FlowFactory())
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_checksum="checksum-active-count",
            definition_json={
                "steps": [
                    {
                        "step_id": str(flow.steps[0].id),
                        "assistant_id": str(flow.steps[0].assistant_id),
                        "step_order": 1,
                    }
                ]
            },
            tenant_id=admin_user.tenant_id,
        )

        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        queued_run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "queued"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )
        running_run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "running"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )
        completed_run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "completed"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )

        claimed = await run_repo.mark_running_if_claimable(
            run_id=running_run.id,
            tenant_id=admin_user.tenant_id,
        )
        assert claimed is True
        await run_repo.update_status(
            run_id=completed_run.id,
            tenant_id=admin_user.tenant_id,
            status=FlowRunStatus.COMPLETED,
        )

        active_count = await run_repo.count_active_runs(tenant_id=admin_user.tenant_id)
        assert active_count == 2

        await run_repo.cancel(run_id=queued_run.id, tenant_id=admin_user.tenant_id)
        active_after_cancel = await run_repo.count_active_runs(tenant_id=admin_user.tenant_id)
        assert active_after_cancel == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_run_rejects_cross_tenant_flow_reference(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows tenant-active-count space", [model.id])
        assistant = await assistant_factory(
            session,
            "Flow tenant-active-count assistant",
            model.id,
            space_id=space.id,
        )

        flow_repo = FlowRepository(session=session, factory=FlowFactory())
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_checksum="checksum-tenant-active-count",
            definition_json={
                "steps": [
                    {
                        "step_id": str(flow.steps[0].id),
                        "assistant_id": str(flow.steps[0].assistant_id),
                        "step_order": 1,
                    }
                ]
            },
            tenant_id=admin_user.tenant_id,
        )

        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "tenant-a"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )
        other_tenant_id = uuid4()
        with pytest.raises(IntegrityError):
            await run_repo.create(
                flow_id=flow.id,
                flow_version=1,
                user_id=admin_user.id,
                tenant_id=other_tenant_id,
                input_payload_json={"case": "tenant-b"},
                preseed_steps=[
                    {
                        "step_id": flow.steps[0].id,
                        "assistant_id": flow.steps[0].assistant_id,
                        "step_order": 1,
                    }
                ],
            )

@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_status_is_idempotent_after_terminal_transition(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows terminal-status space", [model.id])
        assistant = await assistant_factory(
            session,
            "Flow terminal assistant",
            model.id,
            space_id=space.id,
        )

        flow_repo = FlowRepository(session=session, factory=FlowFactory())
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_checksum="checksum-terminal",
            definition_json={
                "steps": [
                    {
                        "step_id": str(flow.steps[0].id),
                        "assistant_id": str(flow.steps[0].assistant_id),
                        "step_order": 1,
                    }
                ]
            },
            tenant_id=admin_user.tenant_id,
        )

        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "status-race"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )
        cancelled = await run_repo.cancel(run_id=run.id, tenant_id=admin_user.tenant_id)
        completed_attempt = await run_repo.update_status(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
            status=FlowRunStatus.COMPLETED,
            output_payload_json={"result": "should-not-overwrite"},
        )

        assert cancelled.status.value == "cancelled"
        assert completed_attempt.status.value == "cancelled"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_claim_step_result_is_single_winner(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows claim space", [model.id])
        assistant = await assistant_factory(
            session,
            "Flow claim assistant",
            model.id,
            space_id=space.id,
        )

        flow_repo = FlowRepository(session=session, factory=FlowFactory())
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_checksum="checksum-claim",
            definition_json={
                "steps": [
                    {
                        "step_id": str(flow.steps[0].id),
                        "assistant_id": str(flow.steps[0].assistant_id),
                        "step_order": 1,
                    }
                ]
            },
            tenant_id=admin_user.tenant_id,
        )
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "cas"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )

        first_claim = await run_repo.claim_step_result(
            run_id=run.id,
            step_id=flow.steps[0].id,
            tenant_id=admin_user.tenant_id,
        )
        second_claim = await run_repo.claim_step_result(
            run_id=run.id,
            step_id=flow.steps[0].id,
            tenant_id=admin_user.tenant_id,
        )

        assert first_claim is not None
        assert second_claim is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_mark_running_if_claimable_is_single_winner(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows run-claim space", [model.id])
        assistant = await assistant_factory(
            session,
            "Flow run-claim assistant",
            model.id,
            space_id=space.id,
        )

        flow_repo = FlowRepository(session=session, factory=FlowFactory())
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_checksum="checksum-run-claim",
            definition_json={
                "steps": [
                    {
                        "step_id": str(flow.steps[0].id),
                        "assistant_id": str(flow.steps[0].assistant_id),
                        "step_order": 1,
                    }
                ]
            },
            tenant_id=admin_user.tenant_id,
        )
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "claim-run"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )

        first = await run_repo.mark_running_if_claimable(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
        )
        second = await run_repo.mark_running_if_claimable(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
        )

        assert first is True
        assert second is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_runs_supports_limit_and_offset(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows run-pagination space", [model.id])
        assistant = await assistant_factory(
            session,
            "Flow pagination assistant",
            model.id,
            space_id=space.id,
        )

        flow_repo = FlowRepository(session=session, factory=FlowFactory())
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_checksum="checksum-run-pagination",
            definition_json={
                "steps": [
                    {
                        "step_id": str(flow.steps[0].id),
                        "assistant_id": str(flow.steps[0].assistant_id),
                        "step_order": 1,
                    }
                ]
            },
            tenant_id=admin_user.tenant_id,
        )
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        for index in range(3):
            await run_repo.create(
                flow_id=flow.id,
                flow_version=1,
                user_id=admin_user.id,
                tenant_id=admin_user.tenant_id,
                input_payload_json={"case": f"run-{index}"},
                preseed_steps=[
                    {
                        "step_id": flow.steps[0].id,
                        "assistant_id": flow.steps[0].assistant_id,
                        "step_order": 1,
                    }
                ],
            )

        first_page = await run_repo.list_runs(
            tenant_id=admin_user.tenant_id,
            flow_id=flow.id,
            limit=1,
            offset=0,
        )
        second_page = await run_repo.list_runs(
            tenant_id=admin_user.tenant_id,
            flow_id=flow.id,
            limit=1,
            offset=1,
        )

        assert len(first_page) == 1
        assert len(second_page) == 1
        assert first_page[0].id != second_page[0].id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_claim_step_result_returns_none_for_wrong_tenant(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows wrong-tenant claim space", [model.id])
        assistant = await assistant_factory(
            session,
            "Flow wrong-tenant assistant",
            model.id,
            space_id=space.id,
        )

        flow_repo = FlowRepository(session=session, factory=FlowFactory())
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_checksum="checksum-wrong-tenant-claim",
            definition_json={
                "steps": [
                    {
                        "step_id": str(flow.steps[0].id),
                        "assistant_id": str(flow.steps[0].assistant_id),
                        "step_order": 1,
                    }
                ]
            },
            tenant_id=admin_user.tenant_id,
        )
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "wrong-tenant-claim"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )

        claimed = await run_repo.claim_step_result(
            run_id=run.id,
            step_id=flow.steps[0].id,
            tenant_id=uuid4(),
        )
        assert claimed is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_or_get_attempt_started_is_idempotent(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows attempt idempotency space", [model.id])
        assistant = await assistant_factory(
            session,
            "Flow attempt idempotency assistant",
            model.id,
            space_id=space.id,
        )

        flow_repo = FlowRepository(session=session, factory=FlowFactory())
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_checksum="checksum-attempt-idempotency",
            definition_json={
                "steps": [
                    {
                        "step_id": str(flow.steps[0].id),
                        "assistant_id": str(flow.steps[0].assistant_id),
                        "step_order": 1,
                    }
                ]
            },
            tenant_id=admin_user.tenant_id,
        )
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "attempt-idempotency"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )
        step_id = flow.steps[0].id

        first = await run_repo.create_or_get_attempt_started(
            run_id=run.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=step_id,
            step_order=1,
            attempt_no=1,
            celery_task_id="task-1",
        )
        second = await run_repo.create_or_get_attempt_started(
            run_id=run.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=step_id,
            step_order=1,
            attempt_no=1,
            celery_task_id="task-1-duplicate",
        )

        assert first.id == second.id
        row_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == run.id)
            .where(FlowStepAttempts.step_id == step_id)
            .where(FlowStepAttempts.attempt_no == 1)
        )
        assert row_count == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_mark_pending_steps_cancelled_only_updates_pending_or_running(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows cancel-step-status space", [model.id])
        assistant = await assistant_factory(
            session,
            "Flow cancel-step-status assistant",
            model.id,
            space_id=space.id,
        )

        flow_repo = FlowRepository(session=session, factory=FlowFactory())
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_checksum="checksum-mark-cancelled",
            definition_json={
                "steps": [
                    {
                        "step_id": str(flow.steps[0].id),
                        "assistant_id": str(flow.steps[0].assistant_id),
                        "step_order": 1,
                    },
                    {
                        "step_id": str(flow.steps[1].id),
                        "assistant_id": str(flow.steps[1].assistant_id),
                        "step_order": 2,
                    },
                ]
            },
            tenant_id=admin_user.tenant_id,
        )
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "mark-cancelled"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                },
                {
                    "step_id": flow.steps[1].id,
                    "assistant_id": flow.steps[1].assistant_id,
                    "step_order": 2,
                },
            ],
        )

        await run_repo.claim_step_result(
            run_id=run.id,
            step_id=flow.steps[0].id,
            tenant_id=admin_user.tenant_id,
        )
        await session.execute(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run.id)
            .where(FlowStepResults.step_id == flow.steps[1].id)
            .values(status=FlowStepResultStatus.COMPLETED.value)
        )
        await session.flush()

        await run_repo.mark_pending_steps_cancelled(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
            error_message="cancelled in test",
        )

        rows = (
            await session.execute(
                sa.select(FlowStepResults)
                .where(FlowStepResults.flow_run_id == run.id)
                .order_by(FlowStepResults.step_order.asc())
            )
        ).scalars().all()
        assert rows[0].status == FlowStepResultStatus.CANCELLED.value
        assert rows[1].status == FlowStepResultStatus.COMPLETED.value


@pytest.mark.asyncio
@pytest.mark.integration
async def test_finish_attempt_is_idempotent(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows finish-attempt space", [model.id])
        assistant = await assistant_factory(
            session,
            "Flow finish-attempt assistant",
            model.id,
            space_id=space.id,
        )

        flow_repo = FlowRepository(session=session, factory=FlowFactory())
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_checksum="checksum-finish-attempt",
            definition_json={
                "steps": [
                    {
                        "step_id": str(flow.steps[0].id),
                        "assistant_id": str(flow.steps[0].assistant_id),
                        "step_order": 1,
                    }
                ]
            },
            tenant_id=admin_user.tenant_id,
        )
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "finish-attempt"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )
        step_id = flow.steps[0].id

        await run_repo.create_or_get_attempt_started(
            run_id=run.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=step_id,
            step_order=1,
            attempt_no=1,
            celery_task_id="task-finish-1",
        )

        first = await run_repo.finish_attempt(
            run_id=run.id,
            step_id=step_id,
            attempt_no=1,
            tenant_id=admin_user.tenant_id,
            status=FlowStepAttemptStatus.COMPLETED,
        )
        second = await run_repo.finish_attempt(
            run_id=run.id,
            step_id=step_id,
            attempt_no=1,
            tenant_id=admin_user.tenant_id,
            status=FlowStepAttemptStatus.COMPLETED,
        )

        assert first is not None
        assert first.finished_at is not None
        assert second is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_and_claim_stale_queued_runs_supports_scope_filters_and_cooldown(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows stale-run scope space", [model.id])
        assistant = await assistant_factory(
            session,
            "Flow stale-run assistant",
            model.id,
            space_id=space.id,
        )

        flow_repo = FlowRepository(session=session, factory=FlowFactory())
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        first_flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        second_flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ).model_copy(update={"name": "Second stale flow"}),
            tenant_id=admin_user.tenant_id,
        )

        await version_repo.create(
            flow_id=first_flow.id,
            version=1,
            definition_checksum="checksum-stale-1",
            definition_json={
                "steps": [
                    {
                        "step_id": str(first_flow.steps[0].id),
                        "assistant_id": str(first_flow.steps[0].assistant_id),
                        "step_order": 1,
                    }
                ]
            },
            tenant_id=admin_user.tenant_id,
        )
        await version_repo.create(
            flow_id=second_flow.id,
            version=1,
            definition_checksum="checksum-stale-2",
            definition_json={
                "steps": [
                    {
                        "step_id": str(second_flow.steps[0].id),
                        "assistant_id": str(second_flow.steps[0].assistant_id),
                        "step_order": 1,
                    }
                ]
            },
            tenant_id=admin_user.tenant_id,
        )

        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        stale_first_flow = await run_repo.create(
            flow_id=first_flow.id,
            flow_version=1,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "stale-first"},
            preseed_steps=[
                {
                    "step_id": first_flow.steps[0].id,
                    "assistant_id": first_flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )
        fresh_first_flow = await run_repo.create(
            flow_id=first_flow.id,
            flow_version=1,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "fresh-first"},
            preseed_steps=[
                {
                    "step_id": first_flow.steps[0].id,
                    "assistant_id": first_flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )
        stale_second_flow = await run_repo.create(
            flow_id=second_flow.id,
            flow_version=1,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "stale-second"},
            preseed_steps=[
                {
                    "step_id": second_flow.steps[0].id,
                    "assistant_id": second_flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )

        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(minutes=5)
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == stale_first_flow.id)
            .values(updated_at=now - timedelta(minutes=10))
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == fresh_first_flow.id)
            .values(updated_at=now - timedelta(minutes=1))
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == stale_second_flow.id)
            .values(updated_at=now - timedelta(minutes=15))
        )
        await session.flush()

        first_flow_stale = await run_repo.list_stale_queued_runs(
            tenant_id=admin_user.tenant_id,
            flow_id=first_flow.id,
            stale_before=stale_before,
            limit=10,
        )
        oldest_only = await run_repo.list_stale_queued_runs(
            tenant_id=admin_user.tenant_id,
            stale_before=stale_before,
            limit=1,
        )
        run_scoped = await run_repo.list_stale_queued_runs(
            tenant_id=admin_user.tenant_id,
            flow_id=first_flow.id,
            run_id=stale_first_flow.id,
            stale_before=stale_before,
            limit=10,
        )

        assert [item.id for item in first_flow_stale] == [stale_first_flow.id]
        assert [item.id for item in oldest_only] == [stale_second_flow.id]
        assert [item.id for item in run_scoped] == [stale_first_flow.id]

        claimed = await run_repo.claim_stale_queued_run_for_redispatch(
            run_id=stale_first_flow.id,
            tenant_id=admin_user.tenant_id,
            stale_before=stale_before,
            flow_id=first_flow.id,
        )
        second_claim = await run_repo.claim_stale_queued_run_for_redispatch(
            run_id=stale_first_flow.id,
            tenant_id=admin_user.tenant_id,
            stale_before=stale_before,
            flow_id=first_flow.id,
        )

        assert claimed is not None
        assert claimed.id == stale_first_flow.id
        assert second_claim is None
