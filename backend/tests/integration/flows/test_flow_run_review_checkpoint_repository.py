from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType
from intric.authentication.principal_types import PrincipalType
from intric.database.tables.flow_tables import (
    FlowRunAuditOutbox,
    FlowRuns,
)
from intric.flows import (
    Flow,
    FlowFactory,
    FlowRepository,
    FlowRun,
    FlowRunReviewCheckpoint,
    FlowStep,
    FlowVersionRepository,
)
from intric.flows.application.flow_run_terminalization import FlowRunTerminalizer
from intric.flows.enums import (
    FlowRunLifecycleSource,
    FlowRunReviewCheckpointState,
    FlowRunStatus,
)
from intric.flows.infrastructure.flow_run_repo import (
    FlowRunRepository,
    flow_run_audit_description,
)
from intric.main.exceptions import BadRequestException


@dataclass(frozen=True, slots=True)
class ReviewCheckpointScenario:
    tenant_id: UUID
    flow_id: UUID
    flow_run_id: UUID
    run: FlowRun
    step_ids: tuple[UUID, UUID]


def _require_uuid(value: UUID | None) -> UUID:
    assert value is not None
    return value


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
        name=f"Review checkpoint flow {uuid4()}",
        description="Flow used for review checkpoint repository tests.",
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
                user_description="Draft answer",
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
                user_description="Use approved answer",
                input_source="previous_step",
                input_type="json",
                input_contract=None,
                output_mode="pass_through",
                output_type="text",
                output_contract=None,
                input_bindings=None,
                output_classification_override=None,
                mcp_policy="inherit",
                input_config=None,
                output_config=None,
            ),
        ],
    )


async def _create_review_checkpoint_scenario(
    *,
    session: AsyncSession,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> ReviewCheckpointScenario:
    model = await completion_model_factory(session, "gpt-4o-mini")
    space = await space_factory(
        session,
        f"Review checkpoint space {uuid4()}",
        [model.id],
    )
    assistant = await assistant_factory(
        session,
        f"Review checkpoint assistant {uuid4()}",
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
    flow = await flow_repo.update(
        flow=flow.model_copy(update={"published_version": 1}),
        tenant_id=admin_user.tenant_id,
    )
    first_step, second_step = flow.steps
    version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
    await version_repo.create(
        flow_id=_require_uuid(flow.id),
        version=1,
        definition_checksum=f"review-checkpoint-{uuid4()}",
        definition_json={
            "steps": [
                {
                    "step_id": str(_require_uuid(first_step.id)),
                    "assistant_id": str(first_step.assistant_id),
                    "step_order": 1,
                },
                {
                    "step_id": str(_require_uuid(second_step.id)),
                    "assistant_id": str(second_step.assistant_id),
                    "step_order": 2,
                },
            ]
        },
        tenant_id=admin_user.tenant_id,
    )

    run_repo = FlowRunRepository(session=session, factory=FlowFactory())
    run = await run_repo.create(
        flow_id=_require_uuid(flow.id),
        flow_version=1,
        user_id=admin_user.id,
        tenant_id=admin_user.tenant_id,
        input_payload_json={"question": "Needs review"},
        preseed_steps=[
            {
                "step_id": _require_uuid(first_step.id),
                "assistant_id": first_step.assistant_id,
                "step_order": 1,
            },
            {
                "step_id": _require_uuid(second_step.id),
                "assistant_id": second_step.assistant_id,
                "step_order": 2,
            },
        ],
    )
    return ReviewCheckpointScenario(
        tenant_id=admin_user.tenant_id,
        flow_id=_require_uuid(flow.id),
        flow_run_id=run.id,
        run=run,
        step_ids=(_require_uuid(first_step.id), _require_uuid(second_step.id)),
    )


async def _create_checkpoint(
    *,
    repo: FlowRunRepository,
    scenario: ReviewCheckpointScenario,
    requester_user_id: UUID,
) -> FlowRunReviewCheckpoint:
    first_step_id, second_step_id = scenario.step_ids
    return await repo.create_or_get_review_checkpoint_for_attempt(
        tenant_id=scenario.tenant_id,
        flow_id=scenario.flow_id,
        flow_run_id=scenario.flow_run_id,
        step_id=first_step_id,
        step_order=1,
        attempt_no=1,
        original_payload_json={"answer": "draft"},
        current_payload_json={"answer": "draft"},
        requester_principal_type=PrincipalType.USER,
        requester_user_id=requester_user_id,
        next_step_ids=(second_step_id,),
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_or_get_review_checkpoint_for_attempt_is_idempotent(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_review_checkpoint_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        repo = FlowRunRepository(session=session, factory=FlowFactory())

        checkpoint = await _create_checkpoint(
            repo=repo,
            scenario=scenario,
            requester_user_id=admin_user.id,
        )
        replayed = await _create_checkpoint(
            repo=repo,
            scenario=scenario,
            requester_user_id=admin_user.id,
        )
        active = await repo.get_active_review_checkpoint(
            run_id=scenario.flow_run_id,
            tenant_id=scenario.tenant_id,
        )

    assert replayed.id == checkpoint.id
    assert active is not None
    assert active.id == checkpoint.id
    assert active.state == FlowRunReviewCheckpointState.AWAITING_REVIEW
    assert active.revision == 1
    assert active.original_payload_json == {"answer": "draft"}
    assert active.current_payload_json == {"answer": "draft"}
    assert active.next_step_ids_json == [scenario.step_ids[1]]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_service_key_run_can_open_review_checkpoint_without_user_requester(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_review_checkpoint_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        repo = FlowRunRepository(session=session, factory=FlowFactory())

        checkpoint = await repo.create_or_get_review_checkpoint_for_attempt(
            tenant_id=scenario.tenant_id,
            flow_id=scenario.flow_id,
            flow_run_id=scenario.flow_run_id,
            step_id=scenario.step_ids[0],
            step_order=1,
            attempt_no=1,
            original_payload_json={"answer": "draft"},
            current_payload_json={"answer": "draft"},
            requester_principal_type=PrincipalType.SERVICE_KEY,
            requester_user_id=None,
            next_step_ids=(scenario.step_ids[1],),
        )

    assert checkpoint.requester_principal_type == PrincipalType.SERVICE_KEY
    assert checkpoint.requester_user_id is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_review_checkpoint_allows_one_active_checkpoint_per_run(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_review_checkpoint_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        repo = FlowRunRepository(session=session, factory=FlowFactory())
        await _create_checkpoint(
            repo=repo,
            scenario=scenario,
            requester_user_id=admin_user.id,
        )

        with pytest.raises(IntegrityError):
            await repo.create_or_get_review_checkpoint_for_attempt(
                tenant_id=scenario.tenant_id,
                flow_id=scenario.flow_id,
                flow_run_id=scenario.flow_run_id,
                step_id=scenario.step_ids[1],
                step_order=2,
                attempt_no=1,
                original_payload_json={"next": "draft"},
                current_payload_json={"next": "draft"},
                requester_principal_type=PrincipalType.USER,
                requester_user_id=admin_user.id,
            )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_review_checkpoint_transition_uses_revision_cas(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_review_checkpoint_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        repo = FlowRunRepository(session=session, factory=FlowFactory())
        checkpoint = await _create_checkpoint(
            repo=repo,
            scenario=scenario,
            requester_user_id=admin_user.id,
        )

        stale = await repo.transition_review_checkpoint_state(
            checkpoint_id=checkpoint.id,
            tenant_id=scenario.tenant_id,
            expected_revision=2,
            allowed_source_states=(FlowRunReviewCheckpointState.AWAITING_REVIEW,),
            target_state=FlowRunReviewCheckpointState.APPROVED,
            decided_by_user_id=admin_user.id,
            decided_by_principal_type=PrincipalType.USER,
        )
        approved = await repo.transition_review_checkpoint_state(
            checkpoint_id=checkpoint.id,
            tenant_id=scenario.tenant_id,
            expected_revision=1,
            allowed_source_states=(FlowRunReviewCheckpointState.AWAITING_REVIEW,),
            target_state=FlowRunReviewCheckpointState.APPROVED,
            decided_by_user_id=admin_user.id,
            decided_by_principal_type=PrincipalType.USER,
        )

    assert stale is None
    assert approved is not None
    assert approved.state == FlowRunReviewCheckpointState.APPROVED
    assert approved.revision == 2
    assert approved.approved_at is not None
    assert approved.decided_by_user_id == admin_user.id
    assert approved.decided_by_principal_type == PrincipalType.USER


@pytest.mark.asyncio
@pytest.mark.integration
async def test_review_checkpoint_outbox_uses_checkpoint_revision_key(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_review_checkpoint_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        repo = FlowRunRepository(session=session, factory=FlowFactory())
        checkpoint = await _create_checkpoint(
            repo=repo,
            scenario=scenario,
            requester_user_id=admin_user.id,
        )

        review_outbox_id = await repo.insert_review_checkpoint_audit_outbox(
            checkpoint=checkpoint,
            run_revision=scenario.run.revision,
            action=ActionType.FLOW_RUN_REVIEW_CHECKPOINT_OPENED,
            actor_id=admin_user.id,
            actor_type=ActorType.USER,
            actor_api_key_id=None,
            source=FlowRunLifecycleSource.REVIEW_CHECKPOINT_OPENED,
            target_state=FlowRunReviewCheckpointState.AWAITING_REVIEW,
        )
        terminal_outbox_id = await repo.insert_terminal_audit_outbox(
            run=scenario.run,
            description=flow_run_audit_description(
                action=ActionType.FLOW_RUN_CANCELLED,
                source=FlowRunLifecycleSource.USER_CANCEL,
            ),
            action=ActionType.FLOW_RUN_CANCELLED,
            entity_type=EntityType.FLOW_RUN,
            actor_id=admin_user.id,
            actor_type=ActorType.USER,
            actor_api_key_id=None,
            source=FlowRunLifecycleSource.USER_CANCEL,
            target_status=FlowRunStatus.CANCELLED,
            error_code="user_cancelled",
            error_message="cancelled in test",
        )
        review_row = await session.scalar(
            sa.select(FlowRunAuditOutbox).where(
                FlowRunAuditOutbox.id == review_outbox_id
            )
        )
        terminal_row = await session.scalar(
            sa.select(FlowRunAuditOutbox).where(
                FlowRunAuditOutbox.id == terminal_outbox_id
            )
        )
        assert review_row is not None
        assert terminal_row is not None
        review_row_values = (
            review_row.review_checkpoint_id,
            review_row.checkpoint_revision,
            review_row.entity_type,
            review_row.entity_id,
        )
        terminal_row_values = (
            terminal_row.review_checkpoint_id,
            terminal_row.run_revision,
        )

        with pytest.raises(IntegrityError):
            await repo.insert_review_checkpoint_audit_outbox(
                checkpoint=checkpoint,
                run_revision=scenario.run.revision,
                action=ActionType.FLOW_RUN_REVIEW_CHECKPOINT_OPENED,
                actor_id=admin_user.id,
                actor_type=ActorType.USER,
                actor_api_key_id=None,
                source=FlowRunLifecycleSource.REVIEW_CHECKPOINT_OPENED,
                target_state=FlowRunReviewCheckpointState.AWAITING_REVIEW,
            )

    assert review_row_values == (
        checkpoint.id,
        checkpoint.revision,
        EntityType.FLOW_RUN_REVIEW_CHECKPOINT.value,
        checkpoint.id,
    )
    assert terminal_row_values == (None, scenario.run.revision)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_mark_running_preserves_original_started_at_on_resume_claim(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_review_checkpoint_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        repo = FlowRunRepository(session=session, factory=FlowFactory())

        first_claim = await repo.mark_running_if_claimable(
            run_id=scenario.flow_run_id,
            tenant_id=scenario.tenant_id,
        )
        first_started_at = await session.scalar(
            sa.select(FlowRuns.started_at).where(FlowRuns.id == scenario.flow_run_id)
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == scenario.flow_run_id)
            .values(status=FlowRunStatus.QUEUED.value)
        )
        second_claim = await repo.mark_running_if_claimable(
            run_id=scenario.flow_run_id,
            tenant_id=scenario.tenant_id,
        )
        second_started_at = await session.scalar(
            sa.select(FlowRuns.started_at).where(FlowRuns.id == scenario.flow_run_id)
        )

    assert first_claim is True
    assert second_claim is True
    assert first_started_at is not None
    assert second_started_at == first_started_at


@pytest.mark.asyncio
@pytest.mark.integration
async def test_awaiting_review_run_can_be_cancelled_by_terminalizer(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_review_checkpoint_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == scenario.flow_run_id)
            .values(status=FlowRunStatus.AWAITING_REVIEW.value)
        )
        repo = FlowRunRepository(session=session, factory=FlowFactory())

        result = await FlowRunTerminalizer(repo).terminalize_run(
            run_id=scenario.flow_run_id,
            tenant_id=scenario.tenant_id,
            target_status=FlowRunStatus.CANCELLED,
            source=FlowRunLifecycleSource.USER_CANCEL,
            error_code="user_cancelled",
            error_message="cancelled in test",
        )

    assert result.did_transition is True
    assert result.run.status == FlowRunStatus.CANCELLED


@pytest.mark.asyncio
@pytest.mark.integration
async def test_awaiting_review_run_rejects_rerun_without_waiting_branch(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_review_checkpoint_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == scenario.flow_run_id)
            .values(status=FlowRunStatus.AWAITING_REVIEW.value)
        )
        repo = FlowRunRepository(session=session, factory=FlowFactory())

        with pytest.raises(BadRequestException) as exc_info:
            await repo.accept_or_replay_rerun_operation(
                tenant_id=scenario.tenant_id,
                flow_id=scenario.flow_id,
                flow_run_id=scenario.flow_run_id,
                rerun_step_id=scenario.step_ids[0],
                rerun_step_order=1,
                request_fingerprint=f"rerun-{uuid4()}",
                expected_run_revision=scenario.run.revision,
                reason="should reject while awaiting review",
                input_payload_json=None,
                step_inputs_json=None,
                requested_by_user_id=admin_user.id,
                invalidated_steps=(),
            )

    assert exc_info.value.code == "flow_run_rerun_invalid_transition"
