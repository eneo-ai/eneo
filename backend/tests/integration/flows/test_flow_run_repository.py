from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from eneo.authentication.auth_models import ApiKeyOwnership, ApiKeyPermission
from eneo.authentication.principal_types import PrincipalType
from eneo.database.database import sessionmanager
from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.flow_tables import (
    FlowRuns,
    FlowStepAttempts,
    FlowStepResults,
)
from eneo.database.tables.service_principals_table import ServicePrincipals
from eneo.flows import FlowFactory, FlowRepository, FlowVersionRepository
from eneo.flows.application.flow_run_recovery_policy import (
    FLOW_DISPATCH_MAX_ATTEMPTS,
)
from eneo.flows.application.flow_run_terminalization import FlowRunTerminalizer
from eneo.flows.domain.flow import (
    Flow,
    FlowRun,
    FlowRunStatus,
    FlowStep,
    FlowStepAttemptStatus,
    FlowStepResult,
    FlowStepResultStatus,
)
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import (
    FlowRunDispatchError,
    FlowRunDispatchErrorKind,
    FlowRunError,
)
from eneo.flows.flow_run_input_envelope import (
    FLOW_INPUT_TRANSCRIPTION_KEY,
    FlowRunInputEnvelopePatch,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_run_rerun_repo import FlowRunRerunRepository
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
)
from eneo.flows.principal import FlowPrincipal


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


async def _insert_service_key(
    session,
    *,
    tenant_id: UUID,
    created_by_user_id: UUID,
    display_name: str,
) -> tuple[UUID, UUID]:
    service_principal_id = uuid4()
    service_key_id = uuid4()
    await session.execute(
        sa.insert(ServicePrincipals).values(
            id=service_principal_id,
            tenant_id=tenant_id,
            display_name=display_name,
            description=None,
            scope_type="tenant",
            scope_id=None,
            state="active",
            created_by_user_id=created_by_user_id,
        )
    )
    await session.execute(
        sa.insert(ApiKeysV2).values(
            id=service_key_id,
            tenant_id=tenant_id,
            ownership=ApiKeyOwnership.SERVICE.value,
            owner_user_id=created_by_user_id,
            service_principal_id=service_principal_id,
            scope_type="tenant",
            scope_id=None,
            permission=ApiKeyPermission.ADMIN.value,
            key_type="api_key",
            key_hash=f"hash-{service_key_id}",
            hash_version="v1",
            key_prefix="test",
            key_suffix=str(service_key_id)[-8:],
            name=f"{display_name} key",
            description=None,
            resource_permissions=None,
            created_by_user_id=created_by_user_id,
        )
    )
    return service_principal_id, service_key_id


async def _insert_rotated_service_key(
    session,
    *,
    tenant_id: UUID,
    created_by_user_id: UUID,
    service_principal_id: UUID,
    rotated_from_key_id: UUID,
) -> UUID:
    service_key_id = uuid4()
    await session.execute(
        sa.insert(ApiKeysV2).values(
            id=service_key_id,
            tenant_id=tenant_id,
            ownership=ApiKeyOwnership.SERVICE.value,
            owner_user_id=created_by_user_id,
            service_principal_id=service_principal_id,
            scope_type="tenant",
            scope_id=None,
            permission=ApiKeyPermission.ADMIN.value,
            key_type="api_key",
            key_hash=f"hash-{service_key_id}",
            hash_version="v1",
            key_prefix="test",
            key_suffix=str(service_key_id)[-8:],
            name="Rotated Flow service key",
            description=None,
            resource_permissions=None,
            created_by_user_id=created_by_user_id,
            rotated_from_key_id=rotated_from_key_id,
        )
    )
    return service_key_id


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
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        await version_repo.create(
            flow_id=flow.id,
            version=1,
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
        flow = flow.model_copy(update={"published_version": 1})
        flow = await flow_repo.update(flow=flow, tenant_id=admin_user.tenant_id)

        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            principal_user_id=admin_user.id,
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
            (
                await session.execute(
                    sa.select(FlowStepResults)
                    .where(FlowStepResults.flow_run_id == run.id)
                    .order_by(FlowStepResults.step_order.asc())
                )
            )
            .scalars()
            .all()
        )

        assert len(rows) == 2
        assert rows[0].step_order == 1
        assert rows[1].step_order == 2
        assert rows[0].status == FlowStepResultStatus.PENDING.value
        assert rows[1].status == FlowStepResultStatus.PENDING.value


@pytest.mark.asyncio
@pytest.mark.integration
async def test_save_step_result_upserts_on_run_and_step(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows run space", [model.id])
        assistant = await assistant_factory(
            session,
            "Run Assistant",
            model.id,
            space_id=space.id,
        )

        flow_repo = FlowRepository(session=session, factory=FlowFactory())
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        step_id = flow.steps[0].id
        assert step_id is not None

        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "assistant_id": str(assistant.id),
                        "step_order": 1,
                    }
                ]
            },
            tenant_id=admin_user.tenant_id,
        )
        run_row = FlowRuns(
            flow_id=flow.id,
            flow_version=1,
            principal_type="user",
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            status="queued",
            input_payload_json={"question": "What happened?"},
        )
        session.add(run_row)
        await session.flush()

        now = datetime.now(timezone.utc)
        first_result = FlowStepResult(
            id=uuid4(),
            flow_run_id=run_row.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=step_id,
            step_order=1,
            assistant_id=assistant.id,
            input_payload_json={"question": "What happened?"},
            effective_prompt="Summarize the incident.",
            output_payload_json={"summary": "First output"},
            model_parameters_json={"model_id": str(model.id), "temperature": 0.2},
            num_tokens_input=11,
            num_tokens_output=9,
            status=FlowStepResultStatus.PENDING,
            error_message=None,
            flow_step_execution_hash="hash-1",
            created_at=now,
            updated_at=now,
        )
        await run_repo.save_step_result(
            flow_run_id=run_row.id,
            result=first_result,
            tenant_id=admin_user.tenant_id,
            attempt_no=None,
        )

        updated_result = FlowStepResult(
            id=uuid4(),
            flow_run_id=run_row.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=step_id,
            step_order=1,
            assistant_id=assistant.id,
            input_payload_json={"question": "What happened?"},
            effective_prompt="Summarize the incident and classify.",
            output_payload_json={"summary": "Updated output", "classification": "open"},
            model_parameters_json={"model_id": str(model.id), "temperature": 0.1},
            num_tokens_input=15,
            num_tokens_output=12,
            status=FlowStepResultStatus.COMPLETED,
            error_message=None,
            flow_step_execution_hash="hash-1",
            created_at=now,
            updated_at=now,
        )
        await run_repo.save_step_result(
            flow_run_id=run_row.id,
            result=updated_result,
            tenant_id=admin_user.tenant_id,
            attempt_no=1,
        )

        count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_row.id)
            .where(FlowStepResults.step_id == step_id)
        )
        assert count == 1

        saved = await run_repo.get_step_result(
            run_id=run_row.id,
            step_id=step_id,
            tenant_id=admin_user.tenant_id,
        )
        assert saved is not None
        assert saved.status == FlowStepResultStatus.COMPLETED
        assert saved.output_payload_json == {
            "summary": "Updated output",
            "classification": "open",
        }
        assert saved.model_parameters_json == {
            "model_id": str(model.id),
            "temperature": 0.1,
        }


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
            principal_user_id=admin_user.id,
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
            principal_user_id=admin_user.id,
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
async def test_list_token_usage_for_runs_sums_provider_usage_across_attempts(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows token usage space", [model.id])
        assistant = await assistant_factory(
            session,
            "Flow token usage assistant",
            model.id,
            space_id=space.id,
        )

        flow_repo = FlowRepository(session=session, factory=FlowFactory())
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        await version_repo.create(
            flow_id=flow.id,
            version=1,
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
        run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "token-usage"},
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

        first_attempt = await run_repo.create_or_get_attempt_started(
            run_id=run.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=flow.steps[0].id,
            step_order=1,
            attempt_no=1,
            celery_task_id="token-usage-failed",
        )
        await run_repo.finish_attempt(
            run_id=run.id,
            step_id=flow.steps[0].id,
            attempt_no=1,
            tenant_id=admin_user.tenant_id,
            status=FlowStepAttemptStatus.FAILED,
            num_tokens_input=10,
            num_tokens_output=4,
        )

        await run_repo.create_or_get_attempt_started(
            run_id=run.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=flow.steps[0].id,
            step_order=1,
            attempt_no=2,
            celery_task_id="token-usage-completed",
            predecessor_attempt_id=first_attempt.id,
        )
        await run_repo.finish_attempt(
            run_id=run.id,
            step_id=flow.steps[0].id,
            attempt_no=2,
            tenant_id=admin_user.tenant_id,
            status=FlowStepAttemptStatus.COMPLETED,
            num_tokens_input=20,
            num_tokens_output=6,
        )

        await run_repo.create_or_get_attempt_started(
            run_id=run.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=flow.steps[1].id,
            step_order=2,
            attempt_no=1,
            celery_task_id="token-usage-partial",
        )
        await run_repo.finish_attempt(
            run_id=run.id,
            step_id=flow.steps[1].id,
            attempt_no=1,
            tenant_id=admin_user.tenant_id,
            status=FlowStepAttemptStatus.COMPLETED,
            num_tokens_input=None,
            num_tokens_output=7,
        )

        usage_by_run_id = await run_repo.list_token_usage_for_runs(
            run_ids=[run.id],
            tenant_id=admin_user.tenant_id,
        )

    usage = usage_by_run_id[run.id]
    assert usage.num_tokens_input == 30
    assert usage.num_tokens_output == 17
    assert usage.num_tokens_total == 47


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_token_usage_for_runs_returns_sparse_map_when_usage_is_empty(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session, "Flows empty token usage space", [model.id]
        )
        assistant = await assistant_factory(
            session,
            "Flow empty token usage assistant",
            model.id,
            space_id=space.id,
        )

        flow_repo = FlowRepository(session=session, factory=FlowFactory())
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        await version_repo.create(
            flow_id=flow.id,
            version=1,
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
        run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "empty-token-usage"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )

        await run_repo.create_or_get_attempt_started(
            run_id=run.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=flow.steps[0].id,
            step_order=1,
            attempt_no=1,
            celery_task_id="empty-token-usage",
        )
        await run_repo.finish_attempt(
            run_id=run.id,
            step_id=flow.steps[0].id,
            attempt_no=1,
            tenant_id=admin_user.tenant_id,
            status=FlowStepAttemptStatus.COMPLETED,
            num_tokens_input=None,
            num_tokens_output=0,
        )

        usage_by_run_id = await run_repo.list_token_usage_for_runs(
            run_ids=[run.id],
            tenant_id=admin_user.tenant_id,
        )

    assert usage_by_run_id == {}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_idempotent_run_returns_existing_run_and_fingerprint(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows idempotent run lookup", [model.id])
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
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_json={"steps": []},
            tenant_id=admin_user.tenant_id,
        )
        flow = flow.model_copy(update={"published_version": 1})
        flow = await flow_repo.update(flow=flow, tenant_id=admin_user.tenant_id)

        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        created = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"question": "What happened?"},
            preseed_steps=[],
            idempotency_key="idem-123",
            request_fingerprint="abc123fingerprint",
        )

        existing = await run_repo.get_idempotent_run(
            tenant_id=admin_user.tenant_id,
            flow_id=flow.id,
            principal=FlowPrincipal(
                principal_type=PrincipalType.USER,
                principal_user_id=admin_user.id,
            ),
            idempotency_key="idem-123",
        )

    assert existing is not None
    existing_run, existing_fingerprint = existing
    assert existing_run.id == created.id
    assert existing_fingerprint == "abc123fingerprint"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_idempotency_key_isolated_between_user_and_service_key_principals(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session, "Flows idempotent principal isolation", [model.id]
        )
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
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_json={"steps": []},
            tenant_id=admin_user.tenant_id,
        )
        flow = flow.model_copy(update={"published_version": 1})
        flow = await flow_repo.update(flow=flow, tenant_id=admin_user.tenant_id)

        service_principal_id, service_key_id = await _insert_service_key(
            session,
            tenant_id=admin_user.tenant_id,
            created_by_user_id=admin_user.id,
            display_name="Flow service principal",
        )

        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        user_run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            principal_type=PrincipalType.USER.value,
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"question": "user"},
            preseed_steps=[],
            idempotency_key="same-key",
            request_fingerprint="user-fingerprint",
        )
        service_key_run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            principal_type=PrincipalType.SERVICE_KEY.value,
            principal_user_id=None,
            principal_service_id=service_principal_id,
            created_by_api_key_id=service_key_id,
            runtime_service_permission=ApiKeyPermission.ADMIN,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"question": "service-key"},
            preseed_steps=[],
            idempotency_key="same-key",
            request_fingerprint="service-key-fingerprint",
        )

        user_existing = await run_repo.get_idempotent_run(
            tenant_id=admin_user.tenant_id,
            flow_id=flow.id,
            idempotency_key="same-key",
            principal=FlowPrincipal(
                principal_type=PrincipalType.USER,
                principal_user_id=admin_user.id,
            ),
        )
        service_key_existing = await run_repo.get_idempotent_run(
            tenant_id=admin_user.tenant_id,
            flow_id=flow.id,
            idempotency_key="same-key",
            principal=FlowPrincipal(
                principal_type=PrincipalType.SERVICE_KEY,
                principal_service_id=service_principal_id,
                actor_api_key_id=service_key_id,
            ),
        )

    assert user_existing is not None
    assert service_key_existing is not None
    assert user_existing[0].id == user_run.id
    assert user_existing[1] == "user-fingerprint"
    assert service_key_existing[0].id == service_key_run.id
    assert service_key_existing[1] == "service-key-fingerprint"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_service_principal_idempotency_replays_after_api_key_rotation(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session, "Flows rotated service idempotency", [model.id]
        )
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
        await FlowVersionRepository(session=session, factory=FlowFactory()).create(
            flow_id=flow.id,
            version=1,
            definition_json={"steps": []},
            tenant_id=admin_user.tenant_id,
        )
        flow = await flow_repo.update(
            flow=flow.model_copy(update={"published_version": 1}),
            tenant_id=admin_user.tenant_id,
        )
        service_principal_id, first_key_id = await _insert_service_key(
            session,
            tenant_id=admin_user.tenant_id,
            created_by_user_id=admin_user.id,
            display_name="Rotated Flow service principal",
        )
        rotated_key_id = await _insert_rotated_service_key(
            session,
            tenant_id=admin_user.tenant_id,
            created_by_user_id=admin_user.id,
            service_principal_id=service_principal_id,
            rotated_from_key_id=first_key_id,
        )
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        created = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            principal_type=PrincipalType.SERVICE_KEY.value,
            principal_user_id=None,
            principal_service_id=service_principal_id,
            created_by_api_key_id=first_key_id,
            runtime_service_permission=ApiKeyPermission.ADMIN,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"question": "first key"},
            preseed_steps=[],
            idempotency_key="rotated-key",
            request_fingerprint="first-key-fingerprint",
        )

        existing = await run_repo.get_idempotent_run(
            tenant_id=admin_user.tenant_id,
            flow_id=flow.id,
            idempotency_key="rotated-key",
            principal=FlowPrincipal(
                principal_type=PrincipalType.SERVICE_KEY,
                principal_service_id=service_principal_id,
                actor_api_key_id=rotated_key_id,
            ),
        )

    assert existing is not None
    assert existing[0].id == created.id
    assert existing[1] == "first-key-fingerprint"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_idempotency_key_isolated_between_service_principals(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session, "Flows service-principal idempotency isolation", [model.id]
        )
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
        await FlowVersionRepository(session=session, factory=FlowFactory()).create(
            flow_id=flow.id,
            version=1,
            definition_json={"steps": []},
            tenant_id=admin_user.tenant_id,
        )
        flow = await flow_repo.update(
            flow=flow.model_copy(update={"published_version": 1}),
            tenant_id=admin_user.tenant_id,
        )
        first_principal_id, first_key_id = await _insert_service_key(
            session,
            tenant_id=admin_user.tenant_id,
            created_by_user_id=admin_user.id,
            display_name="First Flow service principal",
        )
        second_principal_id, second_key_id = await _insert_service_key(
            session,
            tenant_id=admin_user.tenant_id,
            created_by_user_id=admin_user.id,
            display_name="Second Flow service principal",
        )
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        first_run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            principal_type=PrincipalType.SERVICE_KEY.value,
            principal_user_id=None,
            principal_service_id=first_principal_id,
            created_by_api_key_id=first_key_id,
            runtime_service_permission=ApiKeyPermission.ADMIN,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"question": "first service"},
            preseed_steps=[],
            idempotency_key="same-service-key",
            request_fingerprint="first-service-fingerprint",
        )
        second_run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            principal_type=PrincipalType.SERVICE_KEY.value,
            principal_user_id=None,
            principal_service_id=second_principal_id,
            created_by_api_key_id=second_key_id,
            runtime_service_permission=ApiKeyPermission.ADMIN,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"question": "second service"},
            preseed_steps=[],
            idempotency_key="same-service-key",
            request_fingerprint="second-service-fingerprint",
        )

        first_existing = await run_repo.get_idempotent_run(
            tenant_id=admin_user.tenant_id,
            flow_id=flow.id,
            idempotency_key="same-service-key",
            principal=FlowPrincipal(
                principal_type=PrincipalType.SERVICE_KEY,
                principal_service_id=first_principal_id,
                actor_api_key_id=first_key_id,
            ),
        )
        second_existing = await run_repo.get_idempotent_run(
            tenant_id=admin_user.tenant_id,
            flow_id=flow.id,
            idempotency_key="same-service-key",
            principal=FlowPrincipal(
                principal_type=PrincipalType.SERVICE_KEY,
                principal_service_id=second_principal_id,
                actor_api_key_id=second_key_id,
            ),
        )

    assert first_existing is not None
    assert second_existing is not None
    assert first_existing[0].id == first_run.id
    assert first_existing[1] == "first-service-fingerprint"
    assert second_existing[0].id == second_run.id
    assert second_existing[1] == "second-service-fingerprint"


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
            principal_user_id=admin_user.id,
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
            principal_user_id=admin_user.id,
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
            principal_user_id=admin_user.id,
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
            expected_revision=running_run.revision,
        )
        assert claimed is True
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == completed_run.id)
            .values(status=FlowRunStatus.COMPLETED.value)
        )

        active_count = await run_repo.count_active_runs(tenant_id=admin_user.tenant_id)
        assert active_count == 2

        await FlowRunTerminalizer(
            run_repo,
            FlowRunRerunRepository(
                session=run_repo.session,
                factory=run_repo.factory,
            ),
            run_repo.audit_outbox_repo,
            FlowRunReviewCheckpointRepository(
                session=run_repo.session,
                factory=run_repo.factory,
                audit_outbox_repo=run_repo.audit_outbox_repo,
            ),
        ).terminalize_run(
            run_id=queued_run.id,
            tenant_id=admin_user.tenant_id,
            target_status=FlowRunStatus.CANCELLED,
            source=FlowRunLifecycleSource.USER_CANCEL,
            error=FlowRunError.from_source(
                FlowRunLifecycleSource.USER_CANCEL,
                code=FlowApiErrorCode.RUN_USER_CANCELLED,
                message="Run cancelled by user.",
            ),
        )
        active_after_cancel = await run_repo.count_active_runs(
            tenant_id=admin_user.tenant_id
        )
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
        space = await space_factory(
            session, "Flows tenant-active-count space", [model.id]
        )
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
            principal_user_id=admin_user.id,
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
                principal_user_id=admin_user.id,
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
async def test_terminalization_is_idempotent_after_terminal_transition(
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
            principal_user_id=admin_user.id,
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
        terminalizer = FlowRunTerminalizer(
            run_repo,
            FlowRunRerunRepository(
                session=run_repo.session,
                factory=run_repo.factory,
            ),
            run_repo.audit_outbox_repo,
            FlowRunReviewCheckpointRepository(
                session=run_repo.session,
                factory=run_repo.factory,
                audit_outbox_repo=run_repo.audit_outbox_repo,
            ),
        )
        expected_error = FlowRunError.from_source(
            FlowRunLifecycleSource.USER_CANCEL,
            code=FlowApiErrorCode.RUN_USER_CANCELLED,
            message="Run cancelled by user.",
        )
        cancelled = await terminalizer.terminalize_run(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
            target_status=FlowRunStatus.CANCELLED,
            source=FlowRunLifecycleSource.USER_CANCEL,
            error=expected_error,
        )
        completed_attempt = await terminalizer.terminalize_run(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
            target_status=FlowRunStatus.COMPLETED,
            source=FlowRunLifecycleSource.EXECUTOR_COMPLETED,
            output_payload_json={"result": "should-not-overwrite"},
        )

        assert cancelled.run.status.value == "cancelled"
        assert cancelled.did_transition is True
        assert completed_attempt.run.status.value == "cancelled"
        assert completed_attempt.did_transition is False
        refetched = await run_repo.get(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
        )
        assert refetched.error == expected_error


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_sanitizes_corrupt_persisted_run_error_json(
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
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        await version_repo.create(
            flow_id=flow.id,
            version=1,
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
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "corrupt-error-json"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run.id)
            .values(
                status=FlowRunStatus.FAILED.value,
                error_json={
                    "schema_version": 2,
                    "code": "flow_task_failure",
                    "message": "raw provider secret must not leak",
                },
            )
        )
        await session.flush()

        refetched = await run_repo.get(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
        )

        assert refetched.error == FlowRunError(
            code=FlowApiErrorCode.RUN_ERROR_PAYLOAD_INVALID.value,
            message="Persisted flow run error payload is invalid.",
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_failed_terminalization_stamps_active_step_result_error_code(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session, "Flows failed-step-error-code space", [model.id]
        )
        assistant = await assistant_factory(
            session,
            "Flow failed-step-error-code assistant",
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
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "failed-step-error-code"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )
        await run_repo.claim_step_result(
            run_id=run.id,
            step_id=flow.steps[0].id,
            tenant_id=admin_user.tenant_id,
        )

        await FlowRunTerminalizer(
            run_repo,
            FlowRunRerunRepository(
                session=run_repo.session,
                factory=run_repo.factory,
            ),
            run_repo.audit_outbox_repo,
            FlowRunReviewCheckpointRepository(
                session=run_repo.session,
                factory=run_repo.factory,
                audit_outbox_repo=run_repo.audit_outbox_repo,
            ),
        ).terminalize_run(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
            target_status=FlowRunStatus.FAILED,
            source=FlowRunLifecycleSource.EXECUTOR_FAILED,
            error=FlowRunError.from_source(
                FlowRunLifecycleSource.EXECUTOR_FAILED,
                code=FlowApiErrorCode.STEP_EXECUTION_FAILED,
                message="Flow step 1 execution failed.",
            ),
        )

        row = await session.scalar(
            sa.select(FlowStepResults).where(FlowStepResults.flow_run_id == run.id)
        )
        assert row is not None
        assert row.status == FlowStepResultStatus.FAILED.value
        assert row.error_code == FlowApiErrorCode.STEP_EXECUTION_FAILED.value
        assert row.error_message == "Flow step 1 execution failed."


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
            principal_user_id=admin_user.id,
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
        await session.execute(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run.id)
            .where(FlowStepResults.step_id == flow.steps[0].id)
            .values(
                status=FlowStepResultStatus.FAILED.value,
                error_code=FlowApiErrorCode.STEP_EXECUTION_FAILED.value,
                error_message="stale failure",
            )
        )
        await session.flush()

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
        assert first_claim.error_code is None
        assert first_claim.error_message is None
        assert second_claim is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_claim_step_result_is_single_winner_under_concurrency(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session, session.begin():
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows concurrent claim space", [model.id])
        assistant = await assistant_factory(
            session,
            "Flow concurrent claim assistant",
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
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "concurrent-claim"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )
        run_id = run.id
        step_id = flow.steps[0].id
        tenant_id = admin_user.tenant_id

    async def _claim_step() -> UUID | None:
        async with sessionmanager.session() as session, session.begin():
            repo = FlowRunRepository(session=session, factory=FlowFactory())
            claimed = await repo.claim_step_result(
                run_id=run_id,
                step_id=step_id,
                tenant_id=tenant_id,
            )
            return claimed.id if claimed is not None else None

    claim_ids = await asyncio.gather(*[_claim_step() for _ in range(6)])

    non_null_claim_ids = [claim_id for claim_id in claim_ids if claim_id is not None]
    assert len(non_null_claim_ids) == 1

    async with sessionmanager.session() as session, session.begin():
        row = await session.scalar(
            sa.select(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_id)
            .where(FlowStepResults.step_id == step_id)
        )
        assert row is not None
        assert row.status == FlowStepResultStatus.RUNNING.value


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
            principal_user_id=admin_user.id,
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
            expected_revision=run.revision,
        )
        second = await run_repo.mark_running_if_claimable(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
            expected_revision=run.revision,
        )

        assert first is True
        assert second is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_mark_running_if_claimable_is_single_winner_under_concurrency(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session, session.begin():
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session, "Flows concurrent run-claim space", [model.id]
        )
        assistant = await assistant_factory(
            session,
            "Flow concurrent run-claim assistant",
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
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "concurrent-claim-run"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )
        run_id = run.id
        tenant_id = admin_user.tenant_id
        run_revision = run.revision

    async def _claim_run() -> bool:
        async with sessionmanager.session() as session, session.begin():
            repo = FlowRunRepository(session=session, factory=FlowFactory())
            return await repo.mark_running_if_claimable(
                run_id=run_id,
                tenant_id=tenant_id,
                expected_revision=run_revision,
            )

    claim_results = await asyncio.gather(*[_claim_run() for _ in range(6)])

    assert sum(1 for claimed in claim_results if claimed) == 1

    async with sessionmanager.session() as session, session.begin():
        row = await session.scalar(sa.select(FlowRuns).where(FlowRuns.id == run_id))
        assert row is not None
        assert row.status == FlowRunStatus.RUNNING.value


@pytest.mark.asyncio
@pytest.mark.integration
async def test_dispatch_claim_has_one_winner_under_concurrency(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session, session.begin():
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session,
            "Flows concurrent dispatch-claim space",
            [model.id],
        )
        assistant = await assistant_factory(
            session,
            "Flow concurrent dispatch-claim assistant",
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
        await FlowVersionRepository(session=session, factory=FlowFactory()).create(
            flow_id=flow.id,
            version=1,
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
        run = await FlowRunRepository(
            session=session,
            factory=FlowFactory(),
        ).create(
            flow_id=flow.id,
            flow_version=1,
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "concurrent-dispatch-claim"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )
        run_id = run.id
        tenant_id = run.tenant_id
        run_revision = run.revision
        pending_since = run.dispatch_pending_since

    claim_at = datetime.now(timezone.utc)

    async def _claim_dispatch() -> FlowRun | None:
        async with sessionmanager.session() as session, session.begin():
            return await FlowRunRepository(
                session=session,
                factory=FlowFactory(),
            ).claim_queued_run_for_dispatch(
                run_id=run_id,
                tenant_id=tenant_id,
                expected_revision=run_revision,
                now=claim_at,
            )

    claims = await asyncio.gather(*[_claim_dispatch() for _ in range(6)])

    assert sum(claim is not None for claim in claims) == 1
    async with sessionmanager.session() as session, session.begin():
        row = await session.scalar(sa.select(FlowRuns).where(FlowRuns.id == run_id))
        assert row is not None
        assert row.dispatch_attempt_count == 1
        assert row.dispatch_pending_since == pending_since
        assert row.dispatch_next_attempt_at == claim_at + timedelta(seconds=30)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_input_payload_applies_transcription_patch_without_clobbering_claimed_run_state(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows payload-merge space", [model.id])
        assistant = await assistant_factory(
            session,
            "Flow payload-merge assistant",
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
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"file_ids": ["f-1"], "case": "audio-case"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )

        claimed = await run_repo.mark_running_if_claimable(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
            expected_revision=run.revision,
        )
        assert claimed is True

        updated = await run_repo.update_input_payload(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
            input_payload_patch=FlowRunInputEnvelopePatch.transcription(
                transcript="draft transcript",
            ),
        )
        assert updated[FLOW_INPUT_TRANSCRIPTION_KEY] == "draft transcript"

        updated = await run_repo.update_input_payload(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
            input_payload_patch=FlowRunInputEnvelopePatch.transcription(
                transcript="transcribed text",
            ),
        )
        assert updated[FLOW_INPUT_TRANSCRIPTION_KEY] == "transcribed text"

        refreshed = await run_repo.get(run_id=run.id, tenant_id=admin_user.tenant_id)
        assert refreshed.status.value == FlowRunStatus.RUNNING.value
        assert refreshed.input_payload_json == {
            "file_ids": ["f-1"],
            "case": "audio-case",
            FLOW_INPUT_TRANSCRIPTION_KEY: "transcribed text",
        }


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
                principal_user_id=admin_user.id,
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
        space = await space_factory(
            session, "Flows wrong-tenant claim space", [model.id]
        )
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
            principal_user_id=admin_user.id,
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
        space = await space_factory(
            session, "Flows attempt idempotency space", [model.id]
        )
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
            principal_user_id=admin_user.id,
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
async def test_create_or_get_attempt_started_is_single_row_under_concurrency(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session, session.begin():
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session, "Flows concurrent attempt space", [model.id]
        )
        assistant = await assistant_factory(
            session,
            "Flow concurrent attempt assistant",
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
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "concurrent-attempt"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )
        run_id = run.id
        flow_id = flow.id
        step_id = flow.steps[0].id
        tenant_id = admin_user.tenant_id

    async def _start_attempt(worker_name: str) -> UUID:
        async with sessionmanager.session() as session, session.begin():
            repo = FlowRunRepository(session=session, factory=FlowFactory())
            attempt = await repo.create_or_get_attempt_started(
                run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                step_id=step_id,
                step_order=1,
                attempt_no=1,
                celery_task_id=worker_name,
            )
            return attempt.id

    attempt_ids = await asyncio.gather(
        *[_start_attempt(f"task-{index}") for index in range(6)]
    )

    assert len(set(attempt_ids)) == 1

    async with sessionmanager.session() as session, session.begin():
        row_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.step_id == step_id)
            .where(FlowStepAttempts.attempt_no == 1)
        )
        assert row_count == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cancel_terminalization_only_updates_pending_or_running_steps(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session, "Flows cancel-step-status space", [model.id]
        )
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
            principal_user_id=admin_user.id,
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

        await FlowRunTerminalizer(
            run_repo,
            FlowRunRerunRepository(
                session=run_repo.session,
                factory=run_repo.factory,
            ),
            run_repo.audit_outbox_repo,
            FlowRunReviewCheckpointRepository(
                session=run_repo.session,
                factory=run_repo.factory,
                audit_outbox_repo=run_repo.audit_outbox_repo,
            ),
        ).terminalize_run(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
            target_status=FlowRunStatus.CANCELLED,
            source=FlowRunLifecycleSource.USER_CANCEL,
            error=FlowRunError.from_source(
                FlowRunLifecycleSource.USER_CANCEL,
                code=FlowApiErrorCode.RUN_USER_CANCELLED,
                message="cancelled in test",
            ),
        )

        rows = (
            (
                await session.execute(
                    sa.select(FlowStepResults)
                    .where(FlowStepResults.flow_run_id == run.id)
                    .order_by(FlowStepResults.step_order.asc())
                )
            )
            .scalars()
            .all()
        )
        assert rows[0].status == FlowStepResultStatus.CANCELLED.value
        assert rows[0].error_code == FlowApiErrorCode.RUN_USER_CANCELLED.value
        assert rows[1].status == FlowStepResultStatus.COMPLETED.value
        assert rows[1].error_code is None


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
            principal_user_id=admin_user.id,
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
            input_payload_json={"question": "original", "api_key": "super-secret"},
            output_payload_json={"summary": "done"},
        )
        second = await run_repo.finish_attempt(
            run_id=run.id,
            step_id=step_id,
            attempt_no=1,
            tenant_id=admin_user.tenant_id,
            status=FlowStepAttemptStatus.COMPLETED,
            input_payload_json={"question": "overwritten"},
            output_payload_json={"summary": "overwritten"},
        )

        assert first is not None
        assert first.finished_at is not None
        assert first.input_payload_json == {
            "question": "original",
            "api_key": "super-secret",
        }
        assert first.output_payload_json == {"summary": "done"}
        assert second is None
        stored_attempt = await session.scalar(
            sa.select(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == run.id)
            .where(FlowStepAttempts.step_id == step_id)
            .where(FlowStepAttempts.attempt_no == 1)
        )
        assert stored_attempt is not None
        assert stored_attempt.input_payload_json == {
            "question": "original",
            "api_key": "super-secret",
        }
        assert stored_attempt.output_payload_json == {"summary": "done"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_dispatch_lifecycle_uses_one_durable_epoch_and_exact_cas(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session,
            "Flows dispatch lifecycle space",
            [model.id],
        )
        assistant = await assistant_factory(
            session,
            "Flow dispatch lifecycle assistant",
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
            ).model_copy(update={"name": "Second dispatch flow"}),
            tenant_id=admin_user.tenant_id,
        )
        for flow in (first_flow, second_flow):
            await version_repo.create(
                flow_id=flow.id,
                version=1,
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

        async def _create_run(*, flow: Flow, case: str) -> FlowRun:
            return await run_repo.create(
                flow_id=flow.id,
                flow_version=1,
                principal_user_id=admin_user.id,
                tenant_id=admin_user.tenant_id,
                input_payload_json={"case": case},
                preseed_steps=[
                    {
                        "step_id": flow.steps[0].id,
                        "assistant_id": flow.steps[0].assistant_id,
                        "step_order": 1,
                    }
                ],
            )

        due_first = await _create_run(flow=first_flow, case="due-first")
        not_due = await _create_run(flow=first_flow, case="not-due")
        due_second = await _create_run(flow=second_flow, case="due-second")

        for run in (due_first, not_due, due_second):
            assert run.status == FlowRunStatus.QUEUED
            assert run.dispatch_pending_since is not None
            assert run.dispatch_next_attempt_at == run.dispatch_pending_since
            assert run.dispatch_attempt_count == 0
            assert run.dispatch_last_attempt_at is None
            assert run.dispatch_last_error is None
            assert run.dispatched_at is None
            assert run.dispatch_exhausted_at is None

        now = datetime.now(timezone.utc)
        first_pending_since = now - timedelta(minutes=20)
        first_stable_updated_at = now
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == due_first.id)
            .values(
                dispatch_pending_since=first_pending_since,
                dispatch_next_attempt_at=now - timedelta(minutes=5),
                updated_at=first_stable_updated_at,
            )
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == not_due.id)
            .values(
                dispatch_pending_since=now - timedelta(minutes=30),
                dispatch_next_attempt_at=now + timedelta(minutes=5),
                updated_at=now - timedelta(days=1),
            )
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == due_second.id)
            .values(
                dispatch_pending_since=now - timedelta(minutes=25),
                dispatch_next_attempt_at=now - timedelta(minutes=10),
                updated_at=now,
            )
        )
        await session.flush()

        first_flow_due = await run_repo.list_dispatchable_queued_runs(
            tenant_id=admin_user.tenant_id,
            flow_id=first_flow.id,
            due_at=now,
            limit=10,
        )
        oldest_only = await run_repo.list_dispatchable_queued_runs(
            tenant_id=admin_user.tenant_id,
            due_at=now,
            limit=1,
        )
        run_scoped = await run_repo.list_dispatchable_queued_runs(
            tenant_id=admin_user.tenant_id,
            flow_id=first_flow.id,
            run_id=due_first.id,
            due_at=now,
            limit=10,
        )

        assert [item.id for item in first_flow_due] == [due_first.id]
        assert [item.id for item in oldest_only] == [due_second.id]
        assert [item.id for item in run_scoped] == [due_first.id]

        wrong_revision_claim = await run_repo.claim_queued_run_for_dispatch(
            run_id=due_first.id,
            tenant_id=admin_user.tenant_id,
            expected_revision=due_first.revision + 1,
            now=now,
            flow_id=first_flow.id,
        )
        claimed = await run_repo.claim_queued_run_for_dispatch(
            run_id=due_first.id,
            tenant_id=admin_user.tenant_id,
            expected_revision=due_first.revision,
            now=now,
            flow_id=first_flow.id,
        )
        duplicate_claim = await run_repo.claim_queued_run_for_dispatch(
            run_id=due_first.id,
            tenant_id=admin_user.tenant_id,
            expected_revision=due_first.revision,
            now=now,
            flow_id=first_flow.id,
        )

        assert wrong_revision_claim is None
        assert claimed is not None
        assert duplicate_claim is None
        assert claimed.dispatch_attempt_count == 1
        assert claimed.dispatch_last_attempt_at == now
        assert claimed.dispatch_next_attempt_at == now + timedelta(seconds=30)
        assert claimed.dispatch_pending_since == first_pending_since
        assert claimed.updated_at == first_stable_updated_at

        safe_error = FlowRunDispatchError.from_kind(
            FlowRunDispatchErrorKind.EXECUTION_BACKEND_FAILURE
        )
        failure_at = now + timedelta(seconds=1)
        failed = await run_repo.record_dispatch_failure(
            run_id=claimed.id,
            tenant_id=claimed.tenant_id,
            expected_revision=claimed.revision,
            expected_attempt_count=claimed.dispatch_attempt_count,
            error=safe_error,
            now=failure_at,
        )
        assert failed is not None
        assert failed.dispatch_attempt_count == 1
        assert failed.dispatch_last_error == safe_error
        assert failed.dispatch_next_attempt_at == failure_at + timedelta(seconds=30)
        assert failed.dispatch_exhausted_at is None
        assert failed.dispatch_pending_since == first_pending_since
        assert failed.updated_at == first_stable_updated_at

        second_attempt_at = failure_at + timedelta(seconds=31)
        second_attempt = await run_repo.claim_queued_run_for_dispatch(
            run_id=failed.id,
            tenant_id=failed.tenant_id,
            expected_revision=failed.revision,
            now=second_attempt_at,
        )
        assert second_attempt is not None
        accepted_at = second_attempt_at + timedelta(seconds=1)
        accepted = await run_repo.record_dispatch_accepted(
            run_id=second_attempt.id,
            tenant_id=second_attempt.tenant_id,
            expected_revision=second_attempt.revision,
            expected_attempt_count=second_attempt.dispatch_attempt_count,
            now=accepted_at,
        )
        assert accepted is not None
        assert accepted.dispatch_attempt_count == 2
        assert accepted.dispatch_last_attempt_at == second_attempt_at
        assert accepted.dispatch_last_error == safe_error
        assert accepted.dispatch_next_attempt_at == accepted_at + timedelta(seconds=120)
        assert accepted.dispatched_at == accepted_at
        assert accepted.dispatch_pending_since == first_pending_since
        assert accepted.updated_at == first_stable_updated_at

        unknown_outcome_claim = await run_repo.claim_queued_run_for_dispatch(
            run_id=due_second.id,
            tenant_id=due_second.tenant_id,
            expected_revision=due_second.revision,
            now=now,
        )
        assert unknown_outcome_claim is not None
        assert not await run_repo.mark_running_if_claimable(
            run_id=due_second.id,
            tenant_id=due_second.tenant_id,
            expected_revision=due_second.revision + 1,
        )
        assert await run_repo.mark_running_if_claimable(
            run_id=due_second.id,
            tenant_id=due_second.tenant_id,
            expected_revision=due_second.revision,
        )
        assert not await run_repo.mark_running_if_claimable(
            run_id=due_second.id,
            tenant_id=due_second.tenant_id,
            expected_revision=due_second.revision,
        )

        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == not_due.id)
            .values(
                dispatch_attempt_count=FLOW_DISPATCH_MAX_ATTEMPTS,
                dispatch_next_attempt_at=now,
            )
        )
        exhausted = await run_repo.mark_dispatch_exhausted_if_due(
            run_id=not_due.id,
            tenant_id=not_due.tenant_id,
            expected_revision=not_due.revision,
            now=now,
        )
        assert exhausted is not None
        assert exhausted.dispatch_attempt_count == FLOW_DISPATCH_MAX_ATTEMPTS
        assert exhausted.dispatch_next_attempt_at is None
        assert exhausted.dispatch_exhausted_at == now
