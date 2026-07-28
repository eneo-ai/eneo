from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import monotonic
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
    FlowStepAttemptResolvedInputs,
    FlowStepAttempts,
    FlowStepResults,
)
from eneo.database.tables.service_principals_table import ServicePrincipals
from eneo.flows import FlowRepository, FlowVersionRepository
from eneo.flows.application.flow_run_terminalization import FlowRunTerminalizer
from eneo.flows.domain.flow import (
    Flow,
    FlowPersistedJsonObject,
    FlowRun,
    FlowRunStatus,
    FlowStep,
    FlowStepAttempt,
    FlowStepAttemptStatus,
    FlowStepResult,
    FlowStepResultStatus,
)
from eneo.flows.domain.flow_run_exceptions import FlowRunPersistenceInvariantError
from eneo.flows.domain.flow_run_recovery_policy import (
    FLOW_DISPATCH_MAX_ATTEMPTS,
)
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_retention_tombstone import (
    FLOW_RETENTION_ACTOR_SOURCE,
    FlowAttemptRetentionMarker,
    FlowRetentionTombstone,
    RunDebugAttemptRetentionCounts,
)
from eneo.flows.flow_run_error import (
    FlowRunDispatchError,
    FlowRunDispatchErrorKind,
    FlowRunError,
)
from eneo.flows.flow_run_input_envelope import (
    FLOW_INPUT_TRANSCRIPTION_KEY,
    FlowRunInputEnvelopePatch,
)
from eneo.flows.flow_run_provenance import (
    AttemptStartProvenance,
    FlowAttemptProvenanceWriteError,
    FlowResolvedInputEdges,
    FlowResolvedInputEdgesConflictError,
    FlowResolvedInputEdgesUnavailableError,
    ModelParameterSnapshot,
    parse_attempt_provenance,
)
from eneo.flows.infrastructure.flow_run_repo import (
    FlowRunDispatchRedriveGenerationConflict,
    FlowRunRepository,
)
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
                input_config=None,
                output_config=None,
            ),
        ],
    )


def _attempt_retention_marker_payload(
    *,
    tenant_id: UUID,
    run_id: UUID,
    trace_id: UUID,
    object_id: UUID,
) -> FlowPersistedJsonObject:
    now = datetime.now(timezone.utc)
    return FlowAttemptRetentionMarker(
        tombstone=FlowRetentionTombstone(
            tenant_id=str(tenant_id),
            run_id=str(run_id),
            trace_id=str(trace_id),
            data_class="run_debug_evidence",
            object_type="flow_step_attempt",
            object_id=str(object_id),
            policy_source="tenant.flow_settings.retention_policy.run_debug_evidence_days",
            cutoff=now,
            actor_source=FLOW_RETENTION_ACTOR_SOURCE,
            counts=RunDebugAttemptRetentionCounts(
                cleared_field_count=1,
                provider_call_count=0,
                resolved_input_aggregate_count=0,
                resolved_input_edge_count=0,
            ),
            timestamp=now,
            retention_state="retention_purged",
        )
    ).to_payload()


@dataclass(frozen=True)
class _AttemptProvenanceTestContext:
    run_id: UUID
    flow_id: UUID
    step_id: UUID
    tenant_id: UUID
    trace_id: UUID
    attempt_start: AttemptStartProvenance


def _resolved_input_aggregate(*, binding_ref: str) -> FlowResolvedInputEdges:
    return FlowResolvedInputEdges.model_validate(
        {
            "schema_version": 1,
            "edges": [
                {
                    "binding_ref": binding_ref,
                    "source": {
                        "kind": "flow_input",
                        "selector": {"kind": "json_path", "path": ["question"]},
                    },
                    "selection": {
                        "encoding": "utf8",
                        "sha256": "a" * 64,
                        "byte_size": 12,
                    },
                }
            ],
        }
    )


async def _activate_test_attempt(
    *,
    repo: FlowRunRepository,
    context: _AttemptProvenanceTestContext,
    aggregate: FlowResolvedInputEdges,
    attempt_start: AttemptStartProvenance | None = None,
) -> FlowStepAttempt | None:
    return await repo.activate_step_attempt(
        run_id=context.run_id,
        step_id=context.step_id,
        attempt_no=1,
        tenant_id=context.tenant_id,
        resolved_input_edges=aggregate,
        attempt_start=attempt_start,
    )


@pytest.fixture
async def attempt_provenance_context(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> _AttemptProvenanceTestContext:
    async with sessionmanager.session() as session, session.begin():
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session, "Flows attempt provenance space", [model.id]
        )
        assistant = await assistant_factory(
            session,
            "Flow attempt provenance assistant",
            model.id,
            space_id=space.id,
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
                        "assistant_id": str(flow.steps[0].assistant_id),
                        "step_order": 1,
                    }
                ]
            },
            tenant_id=admin_user.tenant_id,
        )
        run = await FlowRunRepository(session=session).create(
            flow_id=flow.id,
            flow_version=1,
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "attempt-provenance"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )
        return _AttemptProvenanceTestContext(
            run_id=run.id,
            flow_id=flow.id,
            step_id=flow.steps[0].id,
            tenant_id=admin_user.tenant_id,
            trace_id=run.trace_id,
            attempt_start=AttemptStartProvenance(
                requested_model="openai/gpt-4o-mini",
                provider="openai",
                deadline_at=datetime.now(timezone.utc) + timedelta(minutes=10),
                resolved_timeout_seconds=600,
                effective_prompt_length=20,
                input_text_length=10,
                input_tokens_estimate=3,
                model_parameter_snapshot=ModelParameterSnapshot(),
            ),
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

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session)
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

        run_repo = FlowRunRepository(session=session)
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

        flow_repo = FlowRepository(session=session)
        run_repo = FlowRunRepository(session=session)
        version_repo = FlowVersionRepository(session=session)
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

        flow_repo = FlowRepository(session=session)
        version_repo = FlowVersionRepository(session=session)

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

        run_repo = FlowRunRepository(session=session)
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
async def test_list_token_usage_for_runs_sums_attempt_usage_across_attempts(
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

        flow_repo = FlowRepository(session=session)
        version_repo = FlowVersionRepository(session=session)
        run_repo = FlowRunRepository(session=session)
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
        step_one_id = flow.steps[0].id
        assert step_one_id is not None
        tenant_id = run.tenant_id

        first_attempt = await run_repo.create_or_get_attempt_started(
            run_id=run.id,
            flow_id=flow.id,
            tenant_id=tenant_id,
            step_id=step_one_id,
            step_order=1,
            attempt_no=1,
            celery_task_id="token-usage-failed",
        )
        cancelled_attempt = await run_repo.finish_attempt(
            run_id=run.id,
            step_id=step_one_id,
            attempt_no=1,
            tenant_id=tenant_id,
            status=FlowStepAttemptStatus.CANCELLED,
            num_tokens_input=10,
            num_tokens_output=4,
        )
        assert cancelled_attempt is not None
        await run_repo.create_or_get_attempt_started(
            run_id=run.id,
            flow_id=flow.id,
            tenant_id=tenant_id,
            step_id=step_one_id,
            step_order=1,
            attempt_no=2,
            celery_task_id="token-usage-completed",
            predecessor_attempt_id=first_attempt.id,
        )
        completed_attempt = await run_repo.finish_attempt(
            run_id=run.id,
            step_id=step_one_id,
            attempt_no=2,
            tenant_id=tenant_id,
            status=FlowStepAttemptStatus.COMPLETED,
            num_tokens_input=20,
            num_tokens_output=6,
        )
        assert completed_attempt is not None
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

        flow_repo = FlowRepository(session=session)
        version_repo = FlowVersionRepository(session=session)
        run_repo = FlowRunRepository(session=session)
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

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session)
        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_json={"steps": []},
            tenant_id=admin_user.tenant_id,
        )
        flow = flow.model_copy(update={"published_version": 1})
        flow = await flow_repo.update(flow=flow, tenant_id=admin_user.tenant_id)

        run_repo = FlowRunRepository(session=session)
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

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session)
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

        run_repo = FlowRunRepository(session=session)
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
        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
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
        run_repo = FlowRunRepository(session=session)
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
        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
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
        run_repo = FlowRunRepository(session=session)
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

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session)
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

        run_repo = FlowRunRepository(session=session)
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
            ),
            run_repo.audit_outbox_repo,
            FlowRunReviewCheckpointRepository(
                session=run_repo.session,
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

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session)
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

        run_repo = FlowRunRepository(session=session)
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

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session)
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

        run_repo = FlowRunRepository(session=session)
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
            ),
            run_repo.audit_outbox_repo,
            FlowRunReviewCheckpointRepository(
                session=run_repo.session,
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

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session)
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

        run_repo = FlowRunRepository(session=session)
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

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session)
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

        run_repo = FlowRunRepository(session=session)
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
            ),
            run_repo.audit_outbox_repo,
            FlowRunReviewCheckpointRepository(
                session=run_repo.session,
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

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session)
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
        run_repo = FlowRunRepository(session=session)
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

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session)
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
        run_repo = FlowRunRepository(session=session)
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
            repo = FlowRunRepository(session=session)
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
async def test_claim_step_result_serializes_against_terminalization(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session, session.begin():
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session, "Flows claim-terminalization race space", [model.id]
        )
        assistant = await assistant_factory(
            session,
            "Flow claim-terminalization race assistant",
            model.id,
            space_id=space.id,
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
                        "assistant_id": str(flow.steps[0].assistant_id),
                        "step_order": 1,
                    }
                ]
            },
            tenant_id=admin_user.tenant_id,
        )
        run = await FlowRunRepository(session=session).create(
            flow_id=flow.id,
            flow_version=1,
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "claim-terminalization-race"},
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

    competing_query_started = asyncio.Event()

    async def _claim_after_terminalization_started() -> FlowStepResult | None:
        async with sessionmanager.session() as session, session.begin():
            sa.event.listen(
                session.sync_session,
                "do_orm_execute",
                lambda _state: competing_query_started.set(),
                once=True,
            )
            return await FlowRunRepository(session=session).claim_step_result(
                run_id=run_id,
                step_id=step_id,
                tenant_id=tenant_id,
            )

    async with sessionmanager.session() as terminal_session:
        async with terminal_session.begin():
            terminal_repo = FlowRunRepository(session=terminal_session)
            terminalized = await FlowRunTerminalizer(
                terminal_repo,
                FlowRunRerunRepository(
                    session=terminal_session,
                ),
                terminal_repo.audit_outbox_repo,
                FlowRunReviewCheckpointRepository(
                    session=terminal_session,
                    audit_outbox_repo=terminal_repo.audit_outbox_repo,
                ),
            ).terminalize_run(
                run_id=run_id,
                tenant_id=tenant_id,
                target_status=FlowRunStatus.FAILED,
                source=FlowRunLifecycleSource.EXECUTOR_FAILED,
                error=FlowRunError.from_source(
                    FlowRunLifecycleSource.EXECUTOR_FAILED,
                    code=FlowApiErrorCode.STEP_EXECUTION_FAILED,
                    message="Terminalization won the race.",
                ),
            )
            assert terminalized.did_transition is True

            claim_task = asyncio.create_task(_claim_after_terminalization_started())
            await asyncio.wait_for(competing_query_started.wait(), timeout=5)
            blocked_before_terminal_commit = not claim_task.done()

        claimed = await asyncio.wait_for(claim_task, timeout=5)

    assert blocked_before_terminal_commit is True
    assert claimed is None
    async with sessionmanager.session() as session, session.begin():
        result_status = await session.scalar(
            sa.select(FlowStepResults.status)
            .where(FlowStepResults.flow_run_id == run_id)
            .where(FlowStepResults.step_id == step_id)
        )
        assert result_status == FlowStepResultStatus.FAILED.value


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

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session)
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
        run_repo = FlowRunRepository(session=session)
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

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session)
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
        run_repo = FlowRunRepository(session=session)
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
            repo = FlowRunRepository(session=session)
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
        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
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
                        "assistant_id": str(flow.steps[0].assistant_id),
                        "step_order": 1,
                    }
                ]
            },
            tenant_id=admin_user.tenant_id,
        )
        run = await FlowRunRepository(
            session=session,
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

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session)
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

        run_repo = FlowRunRepository(session=session)
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

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session)
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
        run_repo = FlowRunRepository(session=session)
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

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session)
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
        run_repo = FlowRunRepository(session=session)
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

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session)
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
        run_repo = FlowRunRepository(session=session)
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
@pytest.mark.parametrize("unavailable_status", ["corrupt", "retention_purged"])
async def test_attempt_provenance_writers_preserve_unavailable_evidence(
    attempt_provenance_context,
    unavailable_status,
):
    context = attempt_provenance_context
    async with sessionmanager.session() as session, session.begin():
        run_repo = FlowRunRepository(session=session)
        attempt = await run_repo.create_or_get_attempt_started(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            step_id=context.step_id,
            step_order=1,
            attempt_no=1,
            celery_task_id=f"{unavailable_status}-attempt-provenance",
        )
        if unavailable_status == "corrupt":
            persisted_provenance = {
                "schema_version": "flow-attempt-provenance.v1",
                "unexpected": {},
            }
        else:
            persisted_provenance = _attempt_retention_marker_payload(
                tenant_id=context.tenant_id,
                run_id=context.run_id,
                trace_id=context.trace_id,
                object_id=attempt.id,
            )
        await session.execute(
            sa.update(FlowStepAttempts)
            .where(FlowStepAttempts.id == attempt.id)
            .values(provenance_json=persisted_provenance)
        )

        with pytest.raises(FlowAttemptProvenanceWriteError) as start_error:
            await run_repo.activate_step_attempt(
                run_id=context.run_id,
                step_id=context.step_id,
                attempt_no=1,
                tenant_id=context.tenant_id,
                resolved_input_edges=_resolved_input_aggregate(
                    binding_ref="unavailable-input"
                ),
                attempt_start=context.attempt_start,
            )
        assert start_error.value.status == unavailable_status
        assert start_error.value.run_id == context.run_id
        assert start_error.value.step_id == context.step_id
        assert start_error.value.attempt_no == 1
        assert start_error.value.tenant_id == context.tenant_id

        persisted = await session.get(FlowStepAttempts, attempt.id)
        assert persisted is not None
        assert persisted.provenance_json == persisted_provenance
        assert (await session.get(FlowStepAttemptResolvedInputs, attempt.id)) is None
        assert persisted.requested_model is None
        assert persisted.provider is None

        finished = await run_repo.finish_attempt(
            run_id=context.run_id,
            step_id=context.step_id,
            attempt_no=1,
            tenant_id=context.tenant_id,
            status=FlowStepAttemptStatus.FAILED,
            provenance_json={
                "schema_version": "flow-attempt-provenance.v1",
                "artifacts": {"generated_count": 1},
            },
            input_payload_json={"secret": "runtime-input"},
            output_payload_json={"secret": "runtime-output"},
        )

        assert finished is not None
        assert finished.provenance_json == persisted_provenance
        if unavailable_status == "retention_purged":
            assert finished.input_payload_json is None
            assert finished.output_payload_json is None
        else:
            assert finished.input_payload_json == {"secret": "runtime-input"}
            assert finished.output_payload_json == {"secret": "runtime-output"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_attempt_provenance_writers_preserve_tracked_sections(
    attempt_provenance_context,
):
    context = attempt_provenance_context
    async with sessionmanager.session() as session, session.begin():
        run_repo = FlowRunRepository(session=session)
        attempt = await run_repo.create_or_get_attempt_started(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            step_id=context.step_id,
            step_order=1,
            attempt_no=1,
            celery_task_id="tracked-attempt-provenance",
        )
        await session.execute(
            sa.update(FlowStepAttempts)
            .where(FlowStepAttempts.id == attempt.id)
            .values(
                provenance_json={
                    "schema_version": "flow-attempt-provenance.v1",
                    "artifacts": {"generated_count": 1},
                }
            )
        )
        for _ in range(2):
            updated = await run_repo.activate_step_attempt(
                run_id=context.run_id,
                step_id=context.step_id,
                attempt_no=1,
                tenant_id=context.tenant_id,
                resolved_input_edges=_resolved_input_aggregate(
                    binding_ref="tracked-input"
                ),
                attempt_start=context.attempt_start,
            )
            assert updated is not None

        persisted = await session.get(FlowStepAttempts, attempt.id)
        assert persisted is not None
        parsed = parse_attempt_provenance(persisted.provenance_json)
        assert parsed.provenance is not None
        assert parsed.provenance.artifacts is not None
        assert parsed.provenance.artifacts.model_dump() == {"generated_count": 1}
        assert parsed.provenance.attempt_start == context.attempt_start
        resolved_input = await run_repo.get_resolved_input_edges(
            attempt_id=attempt.id,
            tenant_id=context.tenant_id,
        )
        assert resolved_input is not None
        assert resolved_input.aggregate == _resolved_input_aggregate(
            binding_ref="tracked-input"
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_resolved_input_edges_are_written_once_with_idempotent_retry(
    attempt_provenance_context,
) -> None:
    context = attempt_provenance_context
    aggregate = _resolved_input_aggregate(binding_ref="question")
    async with sessionmanager.session() as session, session.begin():
        repo = FlowRunRepository(session=session)
        attempt = await repo.create_or_get_attempt_started(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            step_id=context.step_id,
            step_order=1,
            attempt_no=1,
            celery_task_id="resolved-input-write-once",
        )

        legacy = await repo.get_resolved_input_edges(
            attempt_id=attempt.id,
            tenant_id=context.tenant_id,
        )
        assert legacy is not None
        assert legacy.status == "not_tracked"

        written = await _activate_test_attempt(
            repo=repo,
            context=context,
            aggregate=aggregate,
            attempt_start=context.attempt_start,
        )
        assert written is not None
        first_updated_at = await session.scalar(
            sa.select(FlowStepAttemptResolvedInputs.updated_at).where(
                FlowStepAttemptResolvedInputs.flow_step_attempt_id == attempt.id
            )
        )
        identical_retry = await _activate_test_attempt(
            repo=repo,
            context=context,
            aggregate=FlowResolvedInputEdges.model_validate(
                aggregate.model_dump(mode="json")
            ),
            attempt_start=context.attempt_start.model_copy(
                update={
                    "deadline_at": context.attempt_start.deadline_at
                    + timedelta(minutes=5)
                }
            ),
        )
        assert identical_retry is not None
        assert (
            await session.scalar(
                sa.select(FlowStepAttemptResolvedInputs.updated_at).where(
                    FlowStepAttemptResolvedInputs.flow_step_attempt_id == attempt.id
                )
            )
            == first_updated_at
        )
        persisted_attempt = await session.get(FlowStepAttempts, attempt.id)
        assert persisted_attempt is not None
        persisted_provenance = parse_attempt_provenance(
            persisted_attempt.provenance_json
        )
        assert persisted_provenance.provenance is not None
        assert persisted_provenance.provenance.attempt_start == context.attempt_start

        with pytest.raises(FlowResolvedInputEdgesConflictError) as exc_info:
            await _activate_test_attempt(
                repo=repo,
                context=context,
                aggregate=_resolved_input_aggregate(binding_ref="other-question"),
            )
        assert exc_info.value.attempt_id == attempt.id
        assert exc_info.value.tenant_id == context.tenant_id

        persisted = await repo.get_resolved_input_edges(
            attempt_id=attempt.id,
            tenant_id=context.tenant_id,
        )
        assert persisted is not None
        assert persisted.aggregate == aggregate


@pytest.mark.asyncio
@pytest.mark.integration
async def test_resolved_input_edges_reader_marks_corruption_without_repair(
    attempt_provenance_context,
) -> None:
    context = attempt_provenance_context
    corrupt_payload = {"schema_version": 1, "edges": [{}]}
    async with sessionmanager.session() as session, session.begin():
        repo = FlowRunRepository(session=session)
        attempt = await repo.create_or_get_attempt_started(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            step_id=context.step_id,
            step_order=1,
            attempt_no=1,
            celery_task_id="resolved-input-corruption",
        )
        await session.execute(
            sa.insert(FlowStepAttemptResolvedInputs).values(
                flow_step_attempt_id=attempt.id,
                resolved_input_edges_jsonb=corrupt_payload,
            )
        )
        parsed = await repo.get_resolved_input_edges(
            attempt_id=attempt.id,
            tenant_id=context.tenant_id,
        )
        assert parsed is not None
        assert parsed.status == "corrupt"
        assert parsed.aggregate is None

        with pytest.raises(FlowResolvedInputEdgesUnavailableError) as exc_info:
            await _activate_test_attempt(
                repo=repo,
                context=context,
                aggregate=_resolved_input_aggregate(binding_ref="question"),
            )
        assert exc_info.value.attempt_id == attempt.id
        assert exc_info.value.tenant_id == context.tenant_id
        assert exc_info.value.error_code == "flow_resolved_input_edges_invalid_payload"

        persisted = await session.scalar(
            sa.select(FlowStepAttemptResolvedInputs.resolved_input_edges_jsonb).where(
                FlowStepAttemptResolvedInputs.flow_step_attempt_id == attempt.id
            )
        )
        assert persisted == corrupt_payload


@pytest.mark.asyncio
@pytest.mark.integration
async def test_resolved_input_edges_reject_initial_write_after_attempt_terminal(
    attempt_provenance_context,
) -> None:
    context = attempt_provenance_context
    async with sessionmanager.session() as session, session.begin():
        repo = FlowRunRepository(session=session)
        attempt = await repo.create_or_get_attempt_started(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            step_id=context.step_id,
            step_order=1,
            attempt_no=1,
            celery_task_id="resolved-input-terminal-absent",
        )
        await session.execute(
            sa.update(FlowStepAttempts)
            .where(FlowStepAttempts.id == attempt.id)
            .values(
                status=FlowStepAttemptStatus.COMPLETED.value,
                finished_at=datetime.now(timezone.utc),
            )
        )

        written = await _activate_test_attempt(
            repo=repo,
            context=context,
            aggregate=_resolved_input_aggregate(binding_ref="question"),
        )

        assert written is None
        assert (await session.get(FlowStepAttemptResolvedInputs, attempt.id)) is None
        parsed = await repo.get_resolved_input_edges(
            attempt_id=attempt.id,
            tenant_id=context.tenant_id,
        )
        assert parsed is not None
        assert parsed.status == "not_tracked"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("second_binding_ref", "expected_second_result"),
    [("question", "tracked"), ("conflicting-question", "conflict")],
)
async def test_resolved_input_edges_serialize_concurrent_writers(
    attempt_provenance_context,
    second_binding_ref: str,
    expected_second_result: str,
) -> None:
    context = attempt_provenance_context
    aggregate = _resolved_input_aggregate(binding_ref="question")
    async with sessionmanager.session() as session, session.begin():
        attempt = await FlowRunRepository(
            session=session
        ).create_or_get_attempt_started(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            step_id=context.step_id,
            step_order=1,
            attempt_no=1,
            celery_task_id="resolved-input-concurrent",
        )

    second_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    async def _second_write() -> str:
        async with sessionmanager.session() as session, session.begin():
            pid = await session.scalar(sa.select(sa.func.pg_backend_pid()))
            assert pid is not None
            second_pid.set_result(pid)
            try:
                result = await _activate_test_attempt(
                    repo=FlowRunRepository(session=session),
                    context=context,
                    aggregate=_resolved_input_aggregate(binding_ref=second_binding_ref),
                )
            except FlowResolvedInputEdgesConflictError:
                return "conflict"
            assert result is not None
            return "tracked"

    second_task: asyncio.Task[str] | None = None
    try:
        async with sessionmanager.session() as session, session.begin():
            await session.execute(
                sa.select(FlowStepAttempts.id)
                .where(FlowStepAttempts.id == attempt.id)
                .where(FlowStepAttempts.tenant_id == context.tenant_id)
                .with_for_update()
            )
            second_task = asyncio.create_task(_second_write())
            waiting_pid = await second_pid
            deadline = monotonic() + 5
            while monotonic() < deadline:
                is_blocked = await session.scalar(
                    sa.text(
                        "SELECT cardinality(pg_blocking_pids(:waiting_pid)) > 0"
                    ).bindparams(waiting_pid=waiting_pid)
                )
                if is_blocked:
                    break
                await asyncio.sleep(0.02)
            else:
                pytest.fail("second resolved-input writer did not wait on parent lock")

            first_result = await _activate_test_attempt(
                repo=FlowRunRepository(session=session),
                context=context,
                aggregate=aggregate,
            )
            assert first_result is not None

        assert second_task is not None
        assert await second_task == expected_second_result
    finally:
        if second_task is not None and not second_task.done():
            second_task.cancel()

    async with sessionmanager.session() as session, session.begin():
        rows = (
            await session.scalars(
                sa.select(FlowStepAttemptResolvedInputs).where(
                    FlowStepAttemptResolvedInputs.flow_step_attempt_id == attempt.id
                )
            )
        ).all()
        assert len(rows) == 1
        persisted = await FlowRunRepository(session=session).get_resolved_input_edges(
            attempt_id=attempt.id,
            tenant_id=context.tenant_id,
        )
        assert persisted is not None
        assert persisted.aggregate == aggregate


@pytest.mark.asyncio
@pytest.mark.integration
async def test_normal_attempt_hydration_does_not_load_resolved_input_edges(
    attempt_provenance_context,
) -> None:
    context = attempt_provenance_context
    async with sessionmanager.session() as session, session.begin():
        repo = FlowRunRepository(session=session)
        attempt = await repo.create_or_get_attempt_started(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            step_id=context.step_id,
            step_order=1,
            attempt_no=1,
            celery_task_id="resolved-input-deferred",
        )
        await _activate_test_attempt(
            repo=repo,
            context=context,
            aggregate=_resolved_input_aggregate(binding_ref="question"),
        )

    async with sessionmanager.session() as session, session.begin():
        row = await session.scalar(
            sa.select(FlowStepAttempts).where(FlowStepAttempts.id == attempt.id)
        )
        assert row is not None
        await session.refresh(row)
        assert not hasattr(row, "resolved_input_edges_jsonb")
        assert not hasattr(row, "resolved_input_edge_count")
        assert (
            await session.scalar(
                sa.select(
                    FlowStepAttemptResolvedInputs.resolved_input_edge_count
                ).where(
                    FlowStepAttemptResolvedInputs.flow_step_attempt_id == attempt.id
                )
            )
            == 1
        )


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

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session)
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
        run_repo = FlowRunRepository(session=session)
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
            repo = FlowRunRepository(session=session)
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
async def test_attempt_start_serializes_against_terminalization(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session, session.begin():
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session, "Flows attempt-terminalization race space", [model.id]
        )
        assistant = await assistant_factory(
            session,
            "Flow attempt-terminalization race assistant",
            model.id,
            space_id=space.id,
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
                        "assistant_id": str(flow.steps[0].assistant_id),
                        "step_order": 1,
                    }
                ]
            },
            tenant_id=admin_user.tenant_id,
        )
        run = await FlowRunRepository(session=session).create(
            flow_id=flow.id,
            flow_version=1,
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"case": "attempt-terminalization-race"},
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

    competing_query_started = asyncio.Event()

    async def _start_attempt_after_terminalization_started() -> (
        FlowRunPersistenceInvariantError | None
    ):
        async with sessionmanager.session() as session, session.begin():
            sa.event.listen(
                session.sync_session,
                "do_orm_execute",
                lambda _state: competing_query_started.set(),
                once=True,
            )
            try:
                await FlowRunRepository(session=session).create_or_get_attempt_started(
                    run_id=run_id,
                    flow_id=flow_id,
                    tenant_id=tenant_id,
                    step_id=step_id,
                    step_order=1,
                    attempt_no=1,
                    celery_task_id="terminal-race-task",
                )
            except FlowRunPersistenceInvariantError as exc:
                return exc
            return None

    async with sessionmanager.session() as terminal_session:
        async with terminal_session.begin():
            terminal_repo = FlowRunRepository(session=terminal_session)
            terminalized = await FlowRunTerminalizer(
                terminal_repo,
                FlowRunRerunRepository(
                    session=terminal_session,
                ),
                terminal_repo.audit_outbox_repo,
                FlowRunReviewCheckpointRepository(
                    session=terminal_session,
                    audit_outbox_repo=terminal_repo.audit_outbox_repo,
                ),
            ).terminalize_run(
                run_id=run_id,
                tenant_id=tenant_id,
                target_status=FlowRunStatus.FAILED,
                source=FlowRunLifecycleSource.EXECUTOR_FAILED,
                error=FlowRunError.from_source(
                    FlowRunLifecycleSource.EXECUTOR_FAILED,
                    code=FlowApiErrorCode.STEP_ATTEMPT_START_FAILED,
                    message="Terminalization won the race.",
                ),
            )
            assert terminalized.did_transition is True

            attempt_task = asyncio.create_task(
                _start_attempt_after_terminalization_started()
            )
            await asyncio.wait_for(competing_query_started.wait(), timeout=5)
            blocked_before_terminal_commit = not attempt_task.done()

        invariant_error = await asyncio.wait_for(attempt_task, timeout=5)

    assert blocked_before_terminal_commit is True
    assert invariant_error is not None
    assert invariant_error.operation == "create_flow_step_attempt"
    assert invariant_error.run_id == run_id
    assert invariant_error.tenant_id == tenant_id
    assert invariant_error.flow_id == flow_id
    async with sessionmanager.session() as session, session.begin():
        started_attempts = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.status == FlowStepAttemptStatus.STARTED.value)
        )
        assert started_attempts == 0


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

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session)
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
        run_repo = FlowRunRepository(session=session)
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
            ),
            run_repo.audit_outbox_repo,
            FlowRunReviewCheckpointRepository(
                session=run_repo.session,
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

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        version_repo = FlowVersionRepository(session=session)
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
        run_repo = FlowRunRepository(session=session)
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

        flow_repo = FlowRepository(session=session)
        version_repo = FlowVersionRepository(session=session)
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

        run_repo = FlowRunRepository(session=session)

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

        ambiguous_retry = await _create_run(flow=second_flow, case="ambiguous-retry")
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == ambiguous_retry.id)
            .values(
                dispatch_attempt_count=FLOW_DISPATCH_MAX_ATTEMPTS - 1,
                dispatch_last_attempt_at=now - timedelta(minutes=1),
                dispatch_last_error=None,
                dispatch_next_attempt_at=now,
                dispatched_at=None,
            )
        )
        final_ambiguous_claim = await run_repo.claim_queued_run_for_dispatch(
            run_id=ambiguous_retry.id,
            tenant_id=ambiguous_retry.tenant_id,
            expected_revision=ambiguous_retry.revision,
            now=now,
        )
        assert final_ambiguous_claim is not None
        assert (
            final_ambiguous_claim.dispatch_attempt_count == FLOW_DISPATCH_MAX_ATTEMPTS
        )
        assert final_ambiguous_claim.dispatch_last_error is None
        assert final_ambiguous_claim.dispatched_at == now

        ambiguous_then_rejected = await run_repo.record_dispatch_failure(
            run_id=final_ambiguous_claim.id,
            tenant_id=final_ambiguous_claim.tenant_id,
            expected_revision=final_ambiguous_claim.revision,
            expected_attempt_count=final_ambiguous_claim.dispatch_attempt_count,
            error=FlowRunDispatchError.from_kind(
                FlowRunDispatchErrorKind.EXECUTION_BACKEND_FAILURE
            ),
            now=now + timedelta(seconds=1),
        )
        assert ambiguous_then_rejected is not None
        assert ambiguous_then_rejected.dispatch_exhausted_at == now + timedelta(
            seconds=1
        )
        assert ambiguous_then_rejected.dispatched_at == now

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
        assert second_attempt.dispatch_last_error is None
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
        assert accepted.dispatch_last_error is None
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
        unknown_outcome = await run_repo.record_dispatch_outcome_unknown(
            run_id=unknown_outcome_claim.id,
            tenant_id=unknown_outcome_claim.tenant_id,
            expected_revision=unknown_outcome_claim.revision,
            expected_attempt_count=unknown_outcome_claim.dispatch_attempt_count,
            now=now + timedelta(seconds=1),
        )
        assert unknown_outcome is not None
        assert unknown_outcome.status == FlowRunStatus.QUEUED
        assert unknown_outcome.dispatch_last_error is None
        assert unknown_outcome.dispatched_at == now + timedelta(seconds=1)
        assert unknown_outcome.dispatch_next_attempt_at == now + timedelta(seconds=30)
        assert unknown_outcome.dispatch_exhausted_at is None

        accepted_after_unknown_claim = await run_repo.claim_queued_run_for_dispatch(
            run_id=unknown_outcome.id,
            tenant_id=unknown_outcome.tenant_id,
            expected_revision=unknown_outcome.revision,
            now=now + timedelta(seconds=31),
        )
        assert accepted_after_unknown_claim is not None
        accepted_after_unknown = await run_repo.record_dispatch_accepted(
            run_id=accepted_after_unknown_claim.id,
            tenant_id=accepted_after_unknown_claim.tenant_id,
            expected_revision=accepted_after_unknown_claim.revision,
            expected_attempt_count=accepted_after_unknown_claim.dispatch_attempt_count,
            now=now + timedelta(seconds=32),
        )
        assert accepted_after_unknown is not None
        assert accepted_after_unknown.dispatched_at == now + timedelta(seconds=1)

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
                dispatch_last_error=safe_error.model_dump(mode="json"),
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

        never_accepted_redrive = (
            await run_repo.rearm_exhausted_accepted_dispatch_for_redrive(
                run_id=exhausted.id,
                tenant_id=exhausted.tenant_id,
                expected_revision=exhausted.revision,
                expected_dispatch_exhausted_at=exhausted.dispatch_exhausted_at,
                now=now + timedelta(seconds=1),
            )
        )
        assert never_accepted_redrive is None

        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == exhausted.id)
            .values(dispatched_at=now - timedelta(minutes=1))
        )
        missing_generation = (
            await run_repo.rearm_exhausted_accepted_dispatch_for_redrive(
                run_id=exhausted.id,
                tenant_id=exhausted.tenant_id,
                expected_revision=exhausted.revision,
                expected_dispatch_exhausted_at=None,
                now=now + timedelta(seconds=1),
            )
        )
        assert missing_generation == FlowRunDispatchRedriveGenerationConflict(
            current_dispatch_exhausted_at=exhausted.dispatch_exhausted_at
        )

        redrive_at = now + timedelta(seconds=2)
        rearmed = await run_repo.rearm_exhausted_accepted_dispatch_for_redrive(
            run_id=exhausted.id,
            tenant_id=exhausted.tenant_id,
            expected_revision=exhausted.revision,
            expected_dispatch_exhausted_at=exhausted.dispatch_exhausted_at,
            now=redrive_at,
        )
        assert rearmed is not None
        assert rearmed.status == FlowRunStatus.QUEUED
        assert rearmed.dispatch_pending_since == redrive_at
        assert rearmed.dispatch_attempt_count == 0
        assert rearmed.dispatch_last_attempt_at is None
        assert rearmed.dispatch_last_error is None
        assert rearmed.dispatch_next_attempt_at == redrive_at
        assert rearmed.dispatch_exhausted_at is None
        assert rearmed.dispatched_at is None

        stale_retry_during_rearmed_epoch = (
            await run_repo.rearm_exhausted_accepted_dispatch_for_redrive(
                run_id=exhausted.id,
                tenant_id=exhausted.tenant_id,
                expected_revision=exhausted.revision,
                expected_dispatch_exhausted_at=exhausted.dispatch_exhausted_at,
                now=redrive_at + timedelta(seconds=1),
            )
        )
        assert stale_retry_during_rearmed_epoch == (
            FlowRunDispatchRedriveGenerationConflict(current_dispatch_exhausted_at=None)
        )

        later_exhausted_at = redrive_at + timedelta(minutes=1)
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == exhausted.id)
            .values(
                dispatch_attempt_count=FLOW_DISPATCH_MAX_ATTEMPTS,
                dispatch_next_attempt_at=None,
                dispatched_at=redrive_at,
                dispatch_exhausted_at=later_exhausted_at,
            )
        )
        stale_redrive = await run_repo.rearm_exhausted_accepted_dispatch_for_redrive(
            run_id=exhausted.id,
            tenant_id=exhausted.tenant_id,
            expected_revision=exhausted.revision,
            expected_dispatch_exhausted_at=exhausted.dispatch_exhausted_at,
            now=later_exhausted_at + timedelta(seconds=1),
        )
        assert stale_redrive == FlowRunDispatchRedriveGenerationConflict(
            current_dispatch_exhausted_at=later_exhausted_at
        )

        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == exhausted.id)
            .values(status=FlowRunStatus.RUNNING.value)
        )
        converged = await run_repo.rearm_exhausted_accepted_dispatch_for_redrive(
            run_id=exhausted.id,
            tenant_id=exhausted.tenant_id,
            expected_revision=exhausted.revision,
            expected_dispatch_exhausted_at=exhausted.dispatch_exhausted_at,
            now=later_exhausted_at + timedelta(seconds=2),
        )
        assert converged is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_provenance_measurement_and_bounded_attempt_read(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    """The preflight measures exactly, and a narrowed read keeps every current attempt.

    Seeds two steps with rerun history and RAG aggregates of known size, then
    proves the aggregate query returns the exact recorded-passage total, that a
    limited read always includes both current attempts, that history is
    admitted newest-first, and that the byte budget excludes history a row
    limit alone would admit.
    """
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session, "Flow provenance measure space", [model.id]
        )
        assistant = await assistant_factory(
            session, "Flow provenance measure assistant", model.id, space_id=space.id
        )
        flow_repo = FlowRepository(session=session)
        run_repo = FlowRunRepository(session=session)
        flow = await flow_repo.create(
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
            input_payload_json={"case": "provenance-measure"},
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
        tenant_id = run.tenant_id
        step_one, step_two = flow.steps[0].id, flow.steps[1].id
        assert step_one is not None and step_two is not None

        # Step 1: three attempts (1, 2 historical; 3 current). Step 2: one.
        predecessor = None
        for attempt_no in (1, 2, 3):
            attempt = await run_repo.create_or_get_attempt_started(
                run_id=run.id,
                flow_id=flow.id,
                tenant_id=tenant_id,
                step_id=step_one,
                step_order=1,
                attempt_no=attempt_no,
                celery_task_id=f"measure-{attempt_no}",
                predecessor_attempt_id=predecessor.id if predecessor else None,
            )
            predecessor = attempt
        await run_repo.create_or_get_attempt_started(
            run_id=run.id,
            flow_id=flow.id,
            tenant_id=tenant_id,
            step_id=step_two,
            step_order=2,
            attempt_no=1,
            celery_task_id="measure-s2",
        )
        for step_id, step_order, current in ((step_one, 1, 3), (step_two, 2, 1)):
            saved = await run_repo.save_step_result(
                flow_run_id=run.id,
                tenant_id=tenant_id,
                attempt_no=current,
                result_file_references=[],
                result=FlowStepResult(
                    flow_run_id=run.id,
                    flow_id=flow.id,
                    tenant_id=tenant_id,
                    step_id=step_id,
                    step_order=step_order,
                    assistant_id=assistant.id,
                    input_payload_json={"text": "in"},
                    output_payload_json={"text": "out"},
                    status=FlowStepResultStatus.COMPLETED,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                ),
            )
            assert saved is not None

        # Seed RAG aggregates of known size directly: this test owns the
        # repository's SQL semantics; the writer path has its own tests.
        async def set_rag_bytes(step_id, attempt_no, passage_bytes):
            await session.execute(
                sa.update(FlowStepAttempts)
                .where(FlowStepAttempts.flow_run_id == run.id)
                .where(FlowStepAttempts.step_id == step_id)
                .where(FlowStepAttempts.attempt_no == attempt_no)
                .values(
                    provenance_json={
                        "schema_version": "flow-attempt-provenance.v1",
                        "rag": {
                            "status": "success",
                            "recorded_passage_bytes": passage_bytes,
                            "filler": "x" * 2048,
                        },
                    }
                )
            )

        await set_rag_bytes(step_one, 1, 1000)
        await set_rag_bytes(step_one, 2, 2000)
        await set_rag_bytes(step_one, 3, 3000)
        # step 2 attempt 1 keeps no RAG: absent aggregates count as zero.

        size = await run_repo.measure_step_attempt_provenance(
            run_id=run.id, tenant_id=tenant_id
        )
        assert size.attempt_count == 4
        assert size.recorded_passage_bytes == 6000
        # TOAST compresses the repetitive filler far below its logical size —
        # the very reason stored bytes are a materialization floor and must
        # never be reported as a passage count.
        assert 0 < size.stored_provenance_bytes < 3 * 2048

        # A narrowed read keeps both current attempts and admits the newest
        # history first: limit 3 = 2 currents + history slot for (1, 2).
        narrowed = await run_repo.list_step_attempts(
            run_id=run.id,
            tenant_id=tenant_id,
            limit=3,
            history_byte_budget=10 * 1024 * 1024,
        )
        assert [(a.step_order, a.attempt_no) for a in narrowed.attempts] == [
            (1, 2),
            (1, 3),
            (2, 1),
        ]
        assert narrowed.total_count == 4
        assert narrowed.current_total == 2
        assert narrowed.current_admitted == 2

        # Currents consume the byte budget first. A one-byte budget admits the
        # provenance-free current attempt and excludes everything with stored
        # provenance — visibly: the totals still report all four rows and the
        # excluded current attempt.
        tiny_budget = await run_repo.list_step_attempts(
            run_id=run.id,
            tenant_id=tenant_id,
            limit=3,
            history_byte_budget=1,
        )
        assert [(a.step_order, a.attempt_no) for a in tiny_budget.attempts] == [(2, 1)]
        assert tiny_budget.total_count == 4
        assert tiny_budget.current_total == 2
        assert tiny_budget.current_admitted == 1

        # Zero admission still reports every count from the same statement:
        # a zero row limit admits nothing, and the totals do not fall back to
        # a second query on a different snapshot.
        nothing = await run_repo.list_step_attempts(
            run_id=run.id,
            tenant_id=tenant_id,
            limit=0,
            history_byte_budget=1,
        )
        assert nothing.attempts == []
        assert nothing.total_count == 4
        assert nothing.current_total == 2
        assert nothing.current_admitted == 0

        # The logical passage budget catches what compression hides: these
        # aggregates say 6000 passage bytes while TOAST stores them far
        # smaller, so a 2500-byte passage budget must exclude on the logical
        # measure even though every stored-byte check would pass.
        logical = await run_repo.list_step_attempts(
            run_id=run.id,
            tenant_id=tenant_id,
            limit=10,
            history_byte_budget=10 * 1024 * 1024,
            passage_byte_budget=2500,
        )
        admitted_pairs = [(a.step_order, a.attempt_no) for a in logical.attempts]
        # Admission order is currents first — (2,1): 0 bytes, (1,3): 3000 over
        # budget, so only the passage-free current fits.
        assert admitted_pairs == [(2, 1)]
        assert logical.total_count == 4

        # Unlimited read is unchanged: every attempt, oldest first.
        # Corruption in the persisted aggregate must never crash a statement
        # or slip under a size budget as zero. Seed one nonnumeric and one
        # negative value, then prove both readers surface them.
        await session.execute(
            sa.update(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == run.id)
            .where(FlowStepAttempts.step_id == step_one)
            .where(FlowStepAttempts.attempt_no == 1)
            .values(
                provenance_json={
                    "schema_version": "flow-attempt-provenance.v1",
                    "rag": {"status": "success", "recorded_passage_bytes": "12abc"},
                }
            )
        )
        await session.execute(
            sa.update(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == run.id)
            .where(FlowStepAttempts.step_id == step_one)
            .where(FlowStepAttempts.attempt_no == 2)
            .values(
                provenance_json={
                    "schema_version": "flow-attempt-provenance.v1",
                    "rag": {"status": "success", "recorded_passage_bytes": -500},
                }
            )
        )
        corrupt_size = await run_repo.measure_step_attempt_provenance(
            run_id=run.id, tenant_id=tenant_id
        )
        assert corrupt_size.attempt_count == 4
        # Only the intact attempt-3 aggregate still counts toward the total.
        assert corrupt_size.recorded_passage_bytes == 3000
        assert corrupt_size.corrupt_passage_aggregates == 2

        # Under a passage budget, corrupt rows are excluded rather than
        # admitted at a fictitious zero size — and the page says so.
        guarded = await run_repo.list_step_attempts(
            run_id=run.id,
            tenant_id=tenant_id,
            limit=10,
            passage_byte_budget=10 * 1024 * 1024,
        )
        guarded_pairs = [(a.step_order, a.attempt_no) for a in guarded.attempts]
        assert (1, 1) not in guarded_pairs
        assert (1, 2) not in guarded_pairs
        assert guarded.corrupt_passage_aggregates == 2
        assert guarded.total_count == 4

        everything = await run_repo.list_step_attempts(
            run_id=run.id, tenant_id=tenant_id
        )
        assert [(a.step_order, a.attempt_no) for a in everything.attempts] == [
            (1, 1),
            (1, 2),
            (1, 3),
            (2, 1),
        ]
        assert everything.total_count == 4
