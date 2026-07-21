from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers

from eneo.authentication.principal_types import PrincipalType
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    FlowRunRerunInvalidatedSteps,
    FlowRunRerunOperations,
    FlowRunReviewCheckpoints,
    FlowRuns,
    FlowRunStepInputFiles,
    FlowRuntimeUploadedFiles,
    FlowStepAttempts,
    FlowStepResults,
    FlowVersions,
)
from eneo.database.tables.roles_table import Roles
from eneo.database.tables.users_table import users_roles_table
from eneo.flows import FlowRepository, FlowVersionRepository
from eneo.flows.api import flow_run_execution_router
from eneo.flows.application.flow_run_evidence_export_manifest import (
    EVIDENCE_EXPORT_SCHEMA_VERSION,
)
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.enums import (
    FlowOutputType,
    FlowRunRerunInvalidationRole,
    FlowRunRerunOperationStatus,
    FlowRunReviewCheckpointState,
    RerunDependencyKind,
)
from eneo.flows.flow_retention_tombstone import (
    FLOW_RETENTION_ACTOR_SOURCE,
    FlowAttemptRetentionMarker,
    FlowRetentionTombstone,
    RunDebugAttemptRetentionCounts,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode
from eneo.flows.flow_run_provenance import (
    FLOW_ATTEMPT_PROVENANCE_MARKER_SCHEMA_VERSION,
    FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
)
from eneo.flows.published_definition import (
    build_published_definition_json,
    published_definition_checksum,
)
from eneo.main.container.container import Container
from eneo.roles.permissions import Permission
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.users.user import UserAdd, UserInDB, UserState


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
        name="Evidence Contract Flow",
        description="Flow for evidence API integration coverage.",
        created_by_user_id=user_id,
        owner_user_id=user_id,
        published_version=None,
        metadata_json={
            "form_schema": {"fields": [{"name": "question", "type": "string"}]}
        },
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
                user_description="Summarize the case",
                input_source="flow_input",
                input_type="text",
                input_contract=None,
                output_mode="pass_through",
                output_type="json",
                output_contract={"type": "object"},
                input_bindings={"question": "{{flow.input.question}}"},
                output_classification_override=None,
                input_config=None,
                output_config={
                    "url": "https://example.org/hook?token=top-secret",
                    "headers": {
                        "Authorization": "Bearer super-secret",
                        "X-Api-Key": "super-secret",
                    },
                },
            )
        ],
    )


async def _create_user_with_flow_permissions_and_token(
    *,
    db_container,
    tenant_id: UUID,
    role_name_prefix: str,
    permissions: list[Permission],
):
    async with db_container() as container:
        session = container.session()
        user_repo = container.user_repo()
        auth_service = container.auth_service()

        user = await user_repo.add(
            UserAdd(
                email=f"flow-viewer-{uuid4().hex[:8]}@example.com",
                username=f"flow_viewer_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=tenant_id,
            )
        )

        role = Roles(
            name=f"{role_name_prefix} {uuid4().hex[:8]}",
            permissions=[permission.value for permission in permissions],
            tenant_id=tenant_id,
        )
        session.add(role)
        await session.flush()
        await session.execute(
            sa.insert(users_roles_table).values(user_id=user.id, role_id=role.id)
        )
        await session.flush()

        refreshed = await user_repo.get_user_by_email(user.email)
        token = auth_service.create_access_token_for_user(refreshed)
        return refreshed, token


async def _create_view_only_user_and_token(
    *, db_container, patch_auth_service_jwt, tenant_id: UUID
):
    _ = patch_auth_service_jwt
    return await _create_user_with_flow_permissions_and_token(
        db_container=db_container,
        tenant_id=tenant_id,
        role_name_prefix="Flow Viewer",
        permissions=[Permission.FLOWS_VIEW],
    )


async def _create_trace_view_user_and_token(
    *, db_container, patch_auth_service_jwt, tenant_id: UUID
):
    _ = patch_auth_service_jwt
    return await _create_user_with_flow_permissions_and_token(
        db_container=db_container,
        tenant_id=tenant_id,
        role_name_prefix="Flow Trace Viewer",
        permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_TRACE],
    )


async def _add_space_membership(*, db_container, space_id: UUID, user_id: UUID) -> None:
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.text(
                """
                INSERT INTO spaces_users (space_id, user_id, role)
                VALUES (:space_id, :user_id, :role)
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "space_id": str(space_id),
                "user_id": str(user_id),
                "role": SpaceRoleValue.VIEWER.value,
            },
        )


async def _seed_flow_run_contract_data(
    *,
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    attempt_provenance_json: dict[str, Any] | None = None,
    include_rerun_lineage: bool = False,
    include_review_checkpoint_lineage: bool = False,
) -> dict[str, str]:
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Evidence API Space", [model.id])
        await session.execute(
            sa.text(
                """
                INSERT INTO spaces_users (space_id, user_id, role)
                VALUES (:space_id, :user_id, :role)
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "space_id": str(space.id),
                "user_id": str(admin_user.id),
                "role": SpaceRoleValue.VIEWER.value,
            },
        )
        assistant = await assistant_factory(
            session,
            "Evidence API Assistant",
            model.id,
            space_id=space.id,
        )

        flow_repo = FlowRepository(session=session)
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
        step = flow.steps[0]
        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_json={
                "metadata_json": {
                    "ai_builder": {
                        "origin": {
                            "builder_session_id": "builder-session-123",
                        }
                    }
                },
                "steps": [
                    {
                        "step_id": str(step.id),
                        "assistant_id": str(step.assistant_id),
                        "step_order": 1,
                        "output_config": {
                            "url": "https://example.org/hook?token=top-secret",
                            "headers": {
                                "Authorization": "Bearer super-secret",
                                "X-Api-Key": "super-secret",
                            },
                        },
                    }
                ],
            },
            tenant_id=admin_user.tenant_id,
        )
        flow = flow.model_copy(update={"published_version": 1})
        flow = await flow_repo.update(flow=flow, tenant_id=admin_user.tenant_id)

        runtime_input_file = Files(
            name="underlag.pdf",
            text="case file text",
            blob=None,
            checksum="input-checksum",
            size=256,
            mimetype="application/pdf",
            file_type="document",
            transcription=None,
            owner_type="user",
            owner_user_id=admin_user.id,
            owner_service_id=None,
            tenant_id=admin_user.tenant_id,
        )
        session.add(runtime_input_file)
        await session.flush()

        session.add(
            FlowRuntimeUploadedFiles(
                file_id=runtime_input_file.id,
                flow_id=flow.id,
                tenant_id=admin_user.tenant_id,
                uploaded_for_step_id=step.id,
                owner_type="user",
                owner_user_id=admin_user.id,
                owner_service_id=None,
            )
        )
        await session.flush()

        started_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        finished_at = datetime.now(timezone.utc)
        run = FlowRuns(
            flow_id=flow.id,
            flow_version=1,
            principal_type="user",
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            trace_id=uuid4(),
            status="completed",
            input_payload_json={
                "question": "What happened?",
                "api_key": "super-secret",
                "webhook_url": "https://example.org/hook?token=top-secret",
            },
            output_payload_json={"summary": "Completed"},
        )
        session.add(run)
        await session.flush()

        step_result = FlowStepResults(
            flow_run_id=run.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=step.id,
            step_order=1,
            assistant_id=assistant.id,
            current_attempt_no=1,
            input_payload_json={
                "question": "What happened?",
                "token": "super-secret",
                "diagnostics": [{"code": "ok"}],
                "runtime_input": {
                    "file_ids": [str(runtime_input_file.id)],
                    "files_count": 1,
                    "files": [
                        {
                            "id": str(runtime_input_file.id),
                            "name": "json-stale.pdf",
                            "checksum": "json-stale-checksum",
                            "size": 999,
                            "mimetype": "application/pdf",
                            "file_type": "document",
                            "text_length": 999,
                            "has_text": True,
                            "has_transcription": False,
                        }
                    ],
                    "total_file_size": 256,
                    "extracted_text_length": 42,
                    "input_format": "document",
                    "capture_mode": "flow_input_files",
                },
            },
            effective_prompt="Authorization: Bearer super-secret",
            output_payload_json={
                "summary": "Looks good",
                "url": "https://example.org/hook?token=top-secret",
            },
            model_parameters_json={"temperature": 0.2},
            num_tokens_input=11,
            num_tokens_output=7,
            status="completed",
            error_message=None,
            flow_step_execution_hash="hash-1",
        )
        session.add(step_result)
        initial_attempt = FlowStepAttempts(
            flow_run_id=run.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=step.id,
            step_order=1,
            attempt_no=1,
            celery_task_id="celery-1",
            status="completed",
            error_code=None,
            error_message="Bearer super-secret",
            requested_model="gpt-4o-mini",
            response_model="gpt-4o-mini",
            provider="openai",
            finish_reason="stop",
            provider_response_id="resp_123",
            num_tokens_input=11,
            num_tokens_output=7,
            provenance_json=attempt_provenance_json
            or {
                "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
                "llm": {
                    "prompt": "Authorization: Bearer super-secret",
                    "params": {"temperature": 0.2},
                },
                "rag": {
                    "attempted": True,
                    "status": "success",
                    "tracking": {
                        "retrieval_tracked": True,
                        "prompt_context_inclusion_tracked": True,
                        "citation_tracked": False,
                        "material_influence_tracked": False,
                        "selection_basis": "semantic_search_ranked_chunks_grouped_by_source",
                    },
                    "prompt_context": {
                        "tracked": True,
                        "version": 2,
                        "selection_basis": "semantic_search_ranked_chunks_grouped_by_source",
                        "raw_source_count": 1,
                        "raw_chunk_count": 1,
                        "included_source_count": 1,
                        "not_included_source_count": 0,
                        "included_chunk_count": 1,
                        "knowledge_tokens": 64,
                        "truncated_by_token_budget": False,
                        "included_source_ids": ["source-1"],
                        "not_included_source_ids": [],
                        "included_source_titles": [
                            "https://kunskap.example.se/beslut/underlag"
                        ],
                        "included_groups": [
                            {
                                "source_id": "source-1",
                                "source_id_short": "source-1",
                                "source_title": "https://kunskap.example.se/beslut/underlag",
                                "start_chunk": 1,
                                "end_chunk": 1,
                                "chunk_count": 1,
                                "relevance_score": 0.82,
                            }
                        ],
                    },
                    "unique_sources": 1,
                    "references_truncated": False,
                    "reference_metadata_status": "success",
                    "source_names": ["https://kunskap.example.se/beslut/underlag"],
                    "source_display_names": ["kunskap.example.se/beslut/underlag"],
                    "references": [
                        {
                            "id": "source-1",
                            "id_short": "source-1",
                            "title": "https://kunskap.example.se/beslut/underlag",
                            "usage_state": "inserted_into_prompt",
                            "hit_count": 1,
                            "best_score": 0.82,
                            "chunks": [],
                        }
                    ],
                },
                "http": {
                    "request_preview": {"authorization": "Bearer super-secret"},
                },
            },
            started_at=started_at,
            finished_at=finished_at,
        )
        session.add(initial_attempt)
        await session.flush()

        session.add(
            FlowRunStepInputFiles(
                flow_run_id=run.id,
                flow_id=flow.id,
                tenant_id=admin_user.tenant_id,
                step_id=step.id,
                step_order=step.step_order,
                attempt_no=1,
                file_id=runtime_input_file.id,
                ordinal=0,
            )
        )
        await session.flush()

        rerun_operation_id: str | None = None
        rerun_invalidated_step_id: str | None = None
        replacement_attempt_id: str | None = None
        review_checkpoint_id: str | None = None
        if include_review_checkpoint_lineage:
            reviewed_payload = {
                "summary": "Reviewed by human",
                "api_key": "super-secret",
            }
            checkpoint = FlowRunReviewCheckpoints(
                tenant_id=admin_user.tenant_id,
                flow_id=flow.id,
                flow_run_id=run.id,
                step_id=step.id,
                step_order=1,
                attempt_no=1,
                step_label=step.user_description,
                review_mode=FlowStepReviewMode.EDIT.value,
                output_type=FlowOutputType.JSON.value,
                output_contract_json=step.output_contract,
                state=FlowRunReviewCheckpointState.RESUMED.value,
                revision=4,
                schema_version=1,
                original_payload_json=step_result.output_payload_json,
                current_payload_json=reviewed_payload,
                requester_user_id=admin_user.id,
                requester_principal_type=PrincipalType.USER.value,
                decided_by_user_id=admin_user.id,
                decided_by_principal_type=PrincipalType.USER.value,
                next_step_ids_json=[],
                resume_idempotency_key="review-resume-key",
                edited_at=finished_at,
                approved_at=finished_at,
                resumed_at=finished_at,
            )
            step_result.output_payload_json = reviewed_payload
            session.add(checkpoint)
            await session.flush()
            review_checkpoint_id = str(checkpoint.id)
        if include_rerun_lineage:
            rerun_operation = FlowRunRerunOperations(
                tenant_id=admin_user.tenant_id,
                flow_id=flow.id,
                flow_run_id=run.id,
                rerun_step_id=step.id,
                rerun_step_order=1,
                root_attempt_no=2,
                status=FlowRunRerunOperationStatus.COMPLETED.value,
                request_fingerprint="rerun-fingerprint-1",
                expected_run_revision=1,
                accepted_run_revision=2,
                reason="Regenerate evidence lineage.",
                input_payload_json={
                    "question": "What changed?",
                    "api_key": "super-secret",
                },
                root_step_input_override_requested=True,
                requested_by_principal_type=PrincipalType.USER.value,
                requested_by_user_id=admin_user.id,
                failure_code=None,
                failure_message=None,
                started_at=started_at,
                finished_at=finished_at,
            )
            session.add(rerun_operation)
            await session.flush()

            replacement_attempt = FlowStepAttempts(
                flow_run_id=run.id,
                flow_id=flow.id,
                tenant_id=admin_user.tenant_id,
                step_id=step.id,
                step_order=1,
                attempt_no=2,
                rerun_operation_id=rerun_operation.id,
                predecessor_attempt_id=initial_attempt.id,
                celery_task_id="celery-rerun-2",
                status="completed",
                error_code=None,
                error_message=None,
                requested_model="gpt-4o-mini",
                response_model="gpt-4o-mini",
                provider="openai",
                finish_reason="stop",
                provider_response_id="resp_rerun_456",
                num_tokens_input=13,
                num_tokens_output=9,
                provenance_json={
                    "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
                    "llm": {
                        "prompt": "Rerun prompt with token super-secret",
                        "params": {"temperature": 0.1},
                    },
                },
                input_payload_json={"question": "What changed?"},
                output_payload_json={"summary": "Looks good after rerun"},
                flow_step_execution_hash="hash-2",
                started_at=started_at,
                finished_at=finished_at,
            )
            session.add(replacement_attempt)
            await session.flush()
            session.add(
                FlowRunStepInputFiles(
                    flow_run_id=run.id,
                    flow_id=flow.id,
                    tenant_id=admin_user.tenant_id,
                    step_id=step.id,
                    step_order=step.step_order,
                    attempt_no=replacement_attempt.attempt_no,
                    file_id=runtime_input_file.id,
                    ordinal=0,
                )
            )
            await session.flush()

            rerun_operation.root_attempt_id = replacement_attempt.id
            initial_attempt.superseded_by_attempt_id = replacement_attempt.id
            step_result.current_attempt_no = replacement_attempt.attempt_no
            invalidated_step = FlowRunRerunInvalidatedSteps(
                operation_id=rerun_operation.id,
                tenant_id=admin_user.tenant_id,
                flow_id=flow.id,
                flow_run_id=run.id,
                step_id=step.id,
                step_order=1,
                invalidation_order=1,
                role=FlowRunRerunInvalidationRole.ROOT.value,
                dependency_sources_json=[
                    RerunDependencyKind.INPUT_BINDINGS_QUESTION.value
                ],
                prior_step_result_id=step_result.id,
                prior_attempt_id=initial_attempt.id,
                new_attempt_no=replacement_attempt.attempt_no,
                new_attempt_id=replacement_attempt.id,
            )
            session.add(invalidated_step)
            await session.flush()

            rerun_operation_id = str(rerun_operation.id)
            rerun_invalidated_step_id = str(invalidated_step.id)
            replacement_attempt_id = str(replacement_attempt.id)

        seeded: dict[str, str] = {
            "flow_id": str(flow.id),
            "run_id": str(run.id),
            "space_id": str(space.id),
            "trace_id": str(run.trace_id),
        }
        if rerun_operation_id is not None:
            seeded["rerun_operation_id"] = rerun_operation_id
            seeded["rerun_runtime_input_file_id"] = str(runtime_input_file.id)
        if rerun_invalidated_step_id is not None:
            seeded["rerun_invalidated_step_id"] = rerun_invalidated_step_id
        if replacement_attempt_id is not None:
            seeded["replacement_attempt_id"] = replacement_attempt_id
        if review_checkpoint_id is not None:
            seeded["review_checkpoint_id"] = review_checkpoint_id
        return seeded


async def _seed_trace_view_flow_run_contract_data(
    *,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user: UserInDB,
    attempt_provenance_json: dict[str, Any] | None = None,
    include_rerun_lineage: bool = False,
    include_review_checkpoint_lineage: bool = False,
) -> tuple[dict[str, str], UserInDB, str]:
    trace_user, trace_token = await _create_trace_view_user_and_token(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        tenant_id=admin_user.tenant_id,
    )
    seeded = await _seed_flow_run_contract_data(
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=trace_user,
        attempt_provenance_json=attempt_provenance_json,
        include_rerun_lineage=include_rerun_lineage,
        include_review_checkpoint_lineage=include_review_checkpoint_lineage,
    )
    return seeded, trace_user, trace_token


def _attempt_retention_marker_payload(
    *,
    tenant_id: UUID,
    run_id: UUID,
    trace_id: str,
    object_id: UUID,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return FlowAttemptRetentionMarker(
        tombstone=FlowRetentionTombstone(
            tenant_id=str(tenant_id),
            run_id=str(run_id),
            trace_id=trace_id,
            data_class="run_debug_evidence",
            object_type="flow_step_attempt",
            object_id=str(object_id),
            policy_source="tenant.flow_settings.retention_policy.run_debug_evidence_days",
            cutoff=now,
            actor_source=FLOW_RETENTION_ACTOR_SOURCE,
            counts=RunDebugAttemptRetentionCounts(cleared_field_count=1),
            timestamp=now,
            retention_state="retention_purged",
        )
    ).to_payload()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_steps_endpoint_rejects_view_only_access_to_other_users_run(
    client,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    seeded, _, _ = await _seed_trace_view_flow_run_contract_data(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
    )
    viewer, viewer_token = await _create_view_only_user_and_token(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        tenant_id=admin_user.tenant_id,
    )
    await _add_space_membership(
        db_container=db_container,
        space_id=UUID(seeded["space_id"]),
        user_id=viewer.id,
    )

    response = await client.get(
        f"/api/v1/flows/{seeded['flow_id']}/runs/{seeded['run_id']}/steps/",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )

    assert response.status_code == 403, response.text
    payload = response.json()
    assert payload["code"] == "flow_run_access_denied"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_evidence_endpoint_requires_trace_permission(
    client,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    seeded, _, _ = await _seed_trace_view_flow_run_contract_data(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
    )
    viewer, viewer_token = await _create_view_only_user_and_token(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        tenant_id=admin_user.tenant_id,
    )
    await _add_space_membership(
        db_container=db_container,
        space_id=UUID(seeded["space_id"]),
        user_id=viewer.id,
    )

    response = await client.get(
        f"/api/v1/flows/{seeded['flow_id']}/runs/{seeded['run_id']}/evidence/",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "flow_run_access_denied"
    assert response.json()["context"]["auth_layer"] == "flow_run_owner"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_completed_verified_evidence_projects_redacted_structured_result(
    client,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    seeded, _, trace_token = await _seed_trace_view_flow_run_contract_data(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
    )
    output_contract = {
        "type": "object",
        "title": "Evidence result",
        "description": "Bearer schema-secret",
        "properties": {
            "summary": {"type": "string"},
            "api_key": {"type": "string", "title": "Credential-shaped field"},
        },
        "required": ["summary", "api_key"],
    }
    structured_value = {
        "summary": "Completed",
        "api_key": "result-secret",
        "nested": {
            "authorization": "Bearer nested-secret",
            "safe": "preserved",
        },
    }

    async with db_container() as container:
        session = container.session()
        step_result = await session.scalar(
            sa.select(FlowStepResults).where(
                FlowStepResults.flow_run_id == UUID(seeded["run_id"])
            )
        )
        assert step_result is not None
        definition_json = build_published_definition_json(
            flow_id=UUID(seeded["flow_id"]),
            name="Verified evidence flow",
            description=None,
            metadata_json=None,
            steps=[
                {
                    "step_id": str(step_result.step_id),
                    "step_order": step_result.step_order,
                    "assistant_id": str(step_result.assistant_id),
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "json",
                    "output_contract": output_contract,
                }
            ],
        )
        await session.execute(
            sa.update(FlowVersions)
            .where(FlowVersions.flow_id == UUID(seeded["flow_id"]))
            .where(FlowVersions.version == 1)
            .values(
                definition_json=definition_json,
                definition_checksum=published_definition_checksum(definition_json),
            )
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == UUID(seeded["run_id"]))
            .values(output_payload_json={"structured": structured_value})
        )

    run_response = await client.get(
        f"/api/v1/flows/{seeded['flow_id']}/runs/{seeded['run_id']}/",
        headers={"Authorization": f"Bearer {trace_token}"},
    )
    evidence_response = await client.get(
        f"/api/v1/flows/{seeded['flow_id']}/runs/{seeded['run_id']}/evidence/",
        headers={"Authorization": f"Bearer {trace_token}"},
    )

    assert run_response.status_code == 200, run_response.text
    assert evidence_response.status_code == 200, evidence_response.text
    assert run_response.json()["result"] == {
        "kind": "structured",
        "value": structured_value,
        "output_contract": output_contract,
    }
    evidence = evidence_response.json()
    assert evidence["definition_integrity"]["status"] == "verified"
    assert evidence["run"]["result"] == {
        "kind": "structured",
        "value": {
            "summary": "Completed",
            "api_key": "[REDACTED]",
            "nested": {
                "authorization": "[REDACTED]",
                "safe": "preserved",
            },
        },
        "output_contract": {
            "type": "object",
            "title": "Evidence result",
            "description": "Bearer [REDACTED]",
            "properties": {
                "summary": {"type": "string"},
                "api_key": {
                    "type": "string",
                    "title": "Credential-shaped field",
                },
            },
            "required": ["summary", "api_key"],
        },
    }
    assert evidence["run"]["input_payload_json"] == {
        "question": "What happened?",
        "api_key": "[REDACTED]",
        "webhook_url": "https://example.org/hook?token=%5BREDACTED%5D",
    }
    assert evidence["run"]["result_files"] == []
    assert evidence["run"]["token_usage"] is None
    raw_step_payload = evidence["step_results"][0]["output_payload_json"]
    assert raw_step_payload == {
        "summary": "Looks good",
        "url": "https://example.org/hook?token=%5BREDACTED%5D",
    }
    assert raw_step_payload != evidence["run"]["result"]["value"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_completed_invalid_snapshot_remains_inspectable_with_null_result(
    client,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    seeded, _, trace_token = await _seed_trace_view_flow_run_contract_data(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
    )

    response = await client.get(
        f"/api/v1/flows/{seeded['flow_id']}/runs/{seeded['run_id']}/evidence/",
        headers={"Authorization": f"Bearer {trace_token}"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["definition_integrity"]["status"] == "invalid"
    assert payload["definition_snapshot"]["steps"]
    assert payload["run"]["status"] == "completed"
    assert payload["run"]["result"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_evidence_response_accepts_redacted_service_key_credential_id(
    client,
    monkeypatch,
    flow_process_auth_headers,
    create_published_compose_text_flow,
):
    async def _noop_dispatch(
        *, run_id: UUID, tenant_id: UUID, expected_revision: int
    ) -> None:
        _ = (run_id, tenant_id, expected_revision)

    monkeypatch.setattr(
        flow_run_execution_router,
        "dispatch_flow_run_recoverably_after_commit",
        _noop_dispatch,
    )
    flow = await create_published_compose_text_flow(
        client,
        flow_process_auth_headers,
    )
    key_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": f"evidence-result-{uuid4().hex[:8]}",
            "key_type": "sk_",
            "permission": "write",
            "scope_type": "tenant",
            "ownership": "service",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "resource_permissions": {
                "flows": "write",
                "flow_evidence": "write",
            },
        },
        headers=flow_process_auth_headers,
    )
    assert key_response.status_code == 201, key_response.text
    service_key = key_response.json()["secret"]
    create_response = await client.post(
        f"/api/v1/flows/{flow.flow_id}/runs/",
        json={
            "expected_flow_version": flow.published_version,
            "input_payload_json": {"text": "Service-owned evidence"},
        },
        headers={
            "X-API-Key": service_key,
            "Idempotency-Key": f"service-evidence-result:{uuid4().hex}",
        },
    )
    assert create_response.status_code == 201, create_response.text
    run_id = create_response.json()["id"]
    evidence_path = f"/api/v1/flows/{flow.flow_id}/runs/{run_id}/evidence/"

    export_response = await client.get(
        f"{evidence_path}export?format=json",
        headers={"X-API-Key": service_key},
    )
    evidence_response = await client.get(
        evidence_path,
        headers={"X-API-Key": service_key},
    )

    assert export_response.status_code == 200, export_response.text
    assert (
        export_response.json()["bundle"]["run"]["created_by_api_key_id"] == "[REDACTED]"
    )
    assert evidence_response.status_code == 200, evidence_response.text
    evidence_run = evidence_response.json()["run"]
    assert evidence_run["id"] == run_id
    assert evidence_run["status"] == "queued"
    assert evidence_run["result"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_evidence_endpoint_includes_rerun_lineage(
    client,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    seeded, _, trace_token = await _seed_trace_view_flow_run_contract_data(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
        include_rerun_lineage=True,
    )

    response = await client.get(
        f"/api/v1/flows/{seeded['flow_id']}/runs/{seeded['run_id']}/evidence/",
        headers={"Authorization": f"Bearer {trace_token}"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["rerun_operations"][0]["id"] == seeded["rerun_operation_id"]
    assert payload["rerun_operations"][0]["status"] == "completed"
    assert payload["rerun_operations"][0]["root_attempt_no"] == 2
    assert (
        payload["rerun_operations"][0]["root_attempt_id"]
        == seeded["replacement_attempt_id"]
    )
    assert payload["rerun_operations"][0]["expected_run_revision"] == 1
    assert payload["rerun_operations"][0]["accepted_run_revision"] == 2
    assert payload["rerun_operations"][0]["input_payload"]["api_key"] == ("[REDACTED]")
    assert payload["rerun_operations"][0]["root_step_input_override"] == {
        "step_id": payload["rerun_operations"][0]["rerun_step_id"],
        "file_ids": [seeded["rerun_runtime_input_file_id"]],
    }
    assert "input_payload_json" not in payload["rerun_operations"][0]
    assert "step_inputs_json" not in payload["rerun_operations"][0]
    assert (
        payload["rerun_invalidated_steps"][0]["id"]
        == (seeded["rerun_invalidated_step_id"])
    )
    assert payload["rerun_invalidated_steps"][0]["role"] == "root"
    assert payload["rerun_invalidated_steps"][0]["dependency_sources_json"] == [
        "input_bindings.question"
    ]
    assert payload["rerun_invalidated_steps"][0]["new_attempt_no"] == 2
    assert (
        payload["rerun_invalidated_steps"][0]["new_attempt_id"]
        == (seeded["replacement_attempt_id"])
    )
    assert payload["step_results"][0]["current_attempt_no"] == 2
    assert (
        payload["step_attempts"][0]["superseded_by_attempt_id"]
        == (seeded["replacement_attempt_id"])
    )
    assert (
        payload["step_attempts"][1]["rerun_operation_id"]
        == (seeded["rerun_operation_id"])
    )
    assert (
        payload["step_attempts"][1]["predecessor_attempt_id"]
        == (payload["step_attempts"][0]["id"])
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_evidence_endpoint_includes_review_checkpoint_lineage(
    client,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    seeded, _, trace_token = await _seed_trace_view_flow_run_contract_data(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
        include_review_checkpoint_lineage=True,
    )

    response = await client.get(
        f"/api/v1/flows/{seeded['flow_id']}/runs/{seeded['run_id']}/evidence/",
        headers={"Authorization": f"Bearer {trace_token}"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    checkpoint = payload["review_checkpoints"][0]
    assert checkpoint["id"] == seeded["review_checkpoint_id"]
    assert checkpoint["state"] == "resumed"
    assert checkpoint["decision"] == "approved"
    assert checkpoint["revision"] == 4
    assert checkpoint["resume_key_present"] is True
    assert "resume_idempotency_key" not in checkpoint
    assert checkpoint["step_label"] == "Summarize the case"
    assert checkpoint["review_mode"] == "edit"
    assert checkpoint["output_type"] == "json"
    assert "step_snapshot_available" not in checkpoint
    assert checkpoint["output_contract"] == {"type": "object"}
    assert "output_contract_json" not in checkpoint
    assert checkpoint["original_payload_json"]["summary"] == "Looks good"
    assert checkpoint["current_payload_json"]["summary"] == "Reviewed by human"
    assert checkpoint["current_payload_json"]["api_key"] == "[REDACTED]"
    assert (
        payload["step_results"][0]["output_payload_json"]
        == (checkpoint["current_payload_json"])
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_evidence_export_preserves_rerun_lineage_redaction_shape(
    client,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    seeded, _, trace_token = await _seed_trace_view_flow_run_contract_data(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
        include_rerun_lineage=True,
    )

    export_path = (
        f"/api/v1/flows/{seeded['flow_id']}/runs/{seeded['run_id']}/evidence/export"
    )
    redacted_response = await client.get(
        f"{export_path}?format=json",
        headers={"Authorization": f"Bearer {trace_token}"},
    )
    raw_response = await client.get(
        f"{export_path}?format=json&detail=raw&reason=rerun-lineage-audit",
        headers={"Authorization": f"Bearer {trace_token}"},
    )
    repeated_raw_response = await client.get(
        f"{export_path}?format=json&detail=raw&reason=rerun-lineage-audit-repeat",
        headers={"Authorization": f"Bearer {trace_token}"},
    )
    repeated_redacted_response = await client.get(
        f"{export_path}?format=json",
        headers={"Authorization": f"Bearer {trace_token}"},
    )

    assert redacted_response.status_code == 200, redacted_response.text
    assert raw_response.status_code == 200, raw_response.text
    assert repeated_raw_response.status_code == 200
    assert repeated_redacted_response.status_code == 200
    redacted_payload = redacted_response.json()
    raw_payload = raw_response.json()
    repeated_raw_payload = repeated_raw_response.json()
    repeated_redacted_payload = repeated_redacted_response.json()
    redacted_bundle = redacted_payload["bundle"]
    raw_bundle = raw_payload["bundle"]

    assert redacted_payload["schema_version"] == EVIDENCE_EXPORT_SCHEMA_VERSION
    assert raw_payload["schema_version"] == EVIDENCE_EXPORT_SCHEMA_VERSION
    assert (
        redacted_payload["content_hash"] == (repeated_redacted_payload["content_hash"])
    )
    assert raw_payload["content_hash"] == repeated_raw_payload["content_hash"]
    assert set(raw_bundle.keys()) == set(redacted_bundle.keys())
    for section_name in ("rerun_operations", "rerun_invalidated_steps"):
        assert len(raw_bundle[section_name]) == len(redacted_bundle[section_name])
        assert set(raw_bundle[section_name][0].keys()) == set(
            redacted_bundle[section_name][0].keys()
        )

    raw_operation = raw_bundle["rerun_operations"][0]
    redacted_operation = redacted_bundle["rerun_operations"][0]
    assert raw_operation["input_payload_json"]["api_key"] == "super-secret"
    assert redacted_operation["input_payload_json"]["api_key"] == "[REDACTED]"
    assert "step_inputs_json" not in raw_operation
    assert "step_inputs_json" not in redacted_operation
    assert raw_operation["root_step_input_override"] == {
        "step_id": raw_operation["rerun_step_id"],
        "file_ids": [seeded["rerun_runtime_input_file_id"]],
    }
    assert (
        redacted_operation["root_step_input_override"]
        == (raw_operation["root_step_input_override"])
    )
    assert (
        "bundle.rerun_operations[0].input_payload_json.api_key"
        in redacted_payload["redaction"]["masked_paths"]
    )
    assert redacted_payload["summary"]["rerun_lineage"] == {
        "operations_count": 1,
        "queued_operations_count": 0,
        "running_operations_count": 0,
        "completed_operations_count": 1,
        "failed_operations_count": 0,
        "cancelled_operations_count": 0,
        "active_operations_count": 0,
        "terminal_operations_count": 1,
        "invalidated_steps_count": 1,
        "completed_replacement_count": 1,
    }
    assert "rerun_operations" not in redacted_bundle["debug_export"]
    assert "rerun_invalidated_steps" not in redacted_bundle["debug_export"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_evidence_export_preserves_review_checkpoint_lineage(
    client,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    seeded, _, trace_token = await _seed_trace_view_flow_run_contract_data(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
        include_review_checkpoint_lineage=True,
    )

    export_path = (
        f"/api/v1/flows/{seeded['flow_id']}/runs/{seeded['run_id']}/evidence/export"
    )
    redacted_response = await client.get(
        f"{export_path}?format=json",
        headers={"Authorization": f"Bearer {trace_token}"},
    )
    raw_response = await client.get(
        f"{export_path}?format=json&detail=raw&reason=review-lineage-audit",
        headers={"Authorization": f"Bearer {trace_token}"},
    )

    assert redacted_response.status_code == 200, redacted_response.text
    assert raw_response.status_code == 200, raw_response.text
    redacted_payload = redacted_response.json()
    raw_payload = raw_response.json()
    redacted_checkpoint = redacted_payload["bundle"]["review_checkpoints"][0]
    raw_checkpoint = raw_payload["bundle"]["review_checkpoints"][0]

    assert raw_payload["schema_version"] == EVIDENCE_EXPORT_SCHEMA_VERSION
    assert redacted_payload["schema_version"] == EVIDENCE_EXPORT_SCHEMA_VERSION
    assert raw_checkpoint["id"] == seeded["review_checkpoint_id"]
    assert raw_checkpoint["original_payload_json"]["summary"] == "Looks good"
    assert raw_checkpoint["current_payload_json"]["summary"] == "Reviewed by human"
    assert raw_checkpoint["current_payload_json"]["api_key"] == "super-secret"
    assert redacted_checkpoint["current_payload_json"]["api_key"] == "[REDACTED]"
    assert raw_checkpoint["step_label"] == "Summarize the case"
    assert raw_checkpoint["review_mode"] == "edit"
    assert raw_checkpoint["output_type"] == "json"
    assert "step_snapshot_available" not in raw_checkpoint
    assert raw_checkpoint["output_contract"] == {"type": "object"}
    assert "output_contract_json" not in raw_checkpoint
    assert raw_checkpoint["resume_key_present"] is True
    assert "resume_idempotency_key" not in raw_checkpoint
    assert "review-resume-key" not in json.dumps(raw_payload, sort_keys=True)
    assert (
        raw_payload["summary"]["review_checkpoints"]
        == (raw_payload["manifest"]["review_checkpoint_summary"])
    )
    assert "summary_typed" not in raw_payload
    assert "summary_typed" not in redacted_payload
    assert raw_payload["manifest"]["review_checkpoint_summary"] == {
        "count": 1,
        "by_state": {
            "awaiting_review": 0,
            "edited": 0,
            "approved": 0,
            "rejected": 0,
            "resumed": 1,
            "cancelled": 0,
            "expired": 0,
        },
        "any_edited": True,
        "any_resumed": True,
        "active_checkpoint_id": None,
        "active_checkpoint_conflict": False,
    }
    raw_review_impact = raw_payload["summary"]["step_overview"][0]["review_impact"]
    raw_review_event = raw_review_impact["events"][0]
    assert raw_review_impact["checkpoint_count"] == 1
    assert raw_review_impact["any_edited"] is True
    assert raw_review_impact["any_resumed"] is True
    assert raw_review_impact["any_output_changed"] is True
    assert raw_review_impact["last_event"] == raw_review_event
    assert raw_review_event["checkpoint_id"] == seeded["review_checkpoint_id"]
    assert raw_review_event["state"] == "resumed"
    assert raw_review_event["decision"] == "approved"
    assert raw_review_event["attempt_no"] == 1
    assert raw_review_event["revision"] == 4
    assert raw_review_event["output_changed"] is True
    redacted_review_event = redacted_payload["summary"]["step_overview"][0][
        "review_impact"
    ]["events"][0]
    assert redacted_review_event["output_changed"] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_evidence_export_returns_redacted_json_attachment(
    client,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    seeded, trace_user, trace_token = await _seed_trace_view_flow_run_contract_data(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
    )

    response = await client.get(
        f"/api/v1/flows/{seeded['flow_id']}/runs/{seeded['run_id']}/evidence/export?format=json",
        headers={"Authorization": f"Bearer {trace_token}"},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert "attachment;" in response.headers["content-disposition"]
    payload = response.json()
    assert payload["schema_version"] == EVIDENCE_EXPORT_SCHEMA_VERSION
    assert payload["manifest"]["schema_version"] == payload["schema_version"]
    assert payload["manifest"]["run_id"] == seeded["run_id"]
    assert payload["manifest"]["tenant_id"] == str(trace_user.tenant_id)
    assert payload["manifest"]["trace_id"] == seeded["trace_id"]
    assert payload["manifest"]["content_hash"] == payload["content_hash"]
    assert payload["manifest"]["content_hash_input"] == "redacted"
    assert payload["manifest"]["exported_at"] == payload["generated_at"]
    assert payload["manifest"]["detail_mode"] == "redacted"
    assert payload["manifest"]["export_reason"] == "support_debug"
    assert payload["manifest"]["exported_by_user_id"] == str(trace_user.id)
    assert payload["manifest"]["redaction_applied"] is True
    assert payload["manifest"]["provenance_persisted_version_status"] == "tracked"
    assert payload["manifest"]["retention_state_summary"]["tracking_state"] == (
        "not_tracked"
    )
    assert payload["manifest"]["artifact_availability_summary"]["tracking_state"] == (
        "tracked"
    )
    assert payload["manifest"]["artifact_availability_summary"]["artifact_count"] == 0
    assert payload["bundle"]["result_files"] == []
    serialized_bundle = json.dumps(
        payload["bundle"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert payload["content_hash"] == hashlib.sha256(serialized_bundle).hexdigest()
    assert payload["summary"]["status"] == "completed"
    assert payload["summary"]["steps_count"] == 1
    assert payload["summary"]["models_used"] == ["gpt-4o-mini"]
    assert payload["summary"]["rag_source_names"] == [
        "https://kunskap.example.se/beslut/underlag"
    ]
    assert payload["summary"]["rag_source_display_names"] == [
        "kunskap.example.se/beslut/underlag"
    ]
    assert payload["summary"]["rag_usage_tracking"]["retrieval_tracked"] is True
    assert (
        payload["summary"]["rag_usage_tracking"]["tracking_state"]
        == "tracked_with_sources"
    )
    assert (
        payload["summary"]["rag_usage_tracking"]["prompt_context_inclusion_tracked"]
        is True
    )
    assert payload["summary"]["rag_usage_tracking"]["citation_tracked"] is False
    assert payload["summary"]["rag_sources"][0]["usage_state"] == "inserted_into_prompt"
    assert (
        payload["summary"]["rag_sources"][0]["source_container_display_name"]
        == "kunskap.example.se"
    )
    assert (
        payload["summary"]["rag_sources"][0]["source_container_label"]
        == "kunskap.example.se"
    )
    assert payload["summary"]["citations"]["tracking_mode"] == "passive_inline_scan"
    assert payload["summary"]["citations"]["citation_expected"] is False
    assert payload["summary"]["citations"]["citation_observed"] is False
    assert payload["summary"]["citations"]["citation_compliance"] == "not_requested"
    assert payload["summary"]["citations"]["cited_source_ids"] == []
    assert payload["summary"]["citations"]["steps_with_citations_expected"] == 0
    assert payload["summary"]["final_output"]["kind"] == "structured"
    assert payload["summary"]["step_overview"][0]["step_order"] == 1
    assert (
        payload["summary"]["step_overview"][0]["knowledge_retrieval"]["status"]
        == "success"
    )
    assert (
        payload["summary"]["step_overview"][0]["knowledge_retrieval"]["unique_sources"]
        == 1
    )
    assert payload["summary"]["step_overview"][0]["knowledge_retrieval"][
        "prompt_context"
    ]["included_source_ids"] == ["source-1"]
    assert (
        payload["summary"]["step_overview"][0]["knowledge_retrieval"]["prompt_context"][
            "summary"
        ]["total_sources"]
        == 1
    )
    assert payload["summary"]["step_overview"][0]["input_lineage"][
        "runtime_file_names"
    ] == ["underlag.pdf"]
    assert payload["summary"]["step_overview"][0]["input_lineage"][
        "runtime_file_checksums"
    ] == ["input-checksum"]
    runtime_input = payload["bundle"]["step_results"][0]["input_payload_json"][
        "runtime_input"
    ]
    assert runtime_input["files_count"] == 1
    assert runtime_input["total_file_size"] == 256
    assert runtime_input["files"] == [
        {
            "id": str(runtime_input["file_ids"][0]),
            "name": "underlag.pdf",
            "checksum": "input-checksum",
            "size": 256,
            "mimetype": "application/pdf",
            "file_type": "document",
            "text_length": len("case file text"),
            "has_text": True,
            "has_transcription": False,
        }
    ]
    assert (
        payload["summary"]["step_overview"][0]["output_summary"]["preview"]
        == "Looks good"
    )
    assert payload["redaction"]["applied"] is True
    assert payload["redaction"]["policy_version"] == "flow-evidence-redaction.v3"
    assert payload["redaction"]["masked_fields_count"] >= 1
    assert (
        "bundle.run.input_payload_json.api_key" in payload["redaction"]["masked_paths"]
    )
    assert any(
        item["path"] == "bundle.run.input_payload_json.api_key"
        and item["reason"] == "sensitive_key"
        for item in payload["redaction"]["masked_fields"]
    )
    assert (
        "bundle.definition_snapshot.metadata_json.ai_builder.origin.builder_session_id"
        not in payload["redaction"]["masked_paths"]
    )
    assert payload["bundle"]["run"]["trace_id"] == seeded["trace_id"]
    assert payload["bundle"]["run"]["input_payload_json"]["api_key"] == "[REDACTED]"
    assert (
        payload["bundle"]["definition_snapshot"]["metadata_json"]["ai_builder"][
            "origin"
        ]["builder_session_id"]
        == "builder-session-123"
    )
    assert (
        payload["bundle"]["step_results"][0]["effective_prompt"]
        == "Authorization: Bearer [REDACTED]"
    )
    assert (
        payload["bundle"]["definition_snapshot"]["steps"][0]["output_config"][
            "headers"
        ]["Authorization"]
        == "[REDACTED]"
    )
    assert (
        payload["bundle"]["step_attempts"][0]["provenance_json"]["llm"][
            "model_parameters"
        ]["parameter_semantics"]["reasoning_effort"]["mode"]
        == "model_default"
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_evidence_export_marks_corrupt_attempt_provenance(
    client,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    seeded, _, trace_token = await _seed_trace_view_flow_run_contract_data(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
        attempt_provenance_json={"llm": {"prompt": "missing version"}},
    )

    response = await client.get(
        f"/api/v1/flows/{seeded['flow_id']}/runs/{seeded['run_id']}/evidence/export?format=json",
        headers={"Authorization": f"Bearer {trace_token}"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    serialized_bundle = json.dumps(
        payload["bundle"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert payload["content_hash"] == hashlib.sha256(serialized_bundle).hexdigest()
    assert payload["manifest"]["provenance_persisted_version_status"] == "corrupt"
    assert (
        payload["summary"]["rag_usage_tracking"]["tracking_state"] == "unknown_corrupt"
    )
    assert payload["summary"]["rag_usage_tracking"]["retrieval_tracked"] is False
    marker = payload["bundle"]["step_attempts"][0]["provenance_json"]
    assert marker["schema_version"] == FLOW_ATTEMPT_PROVENANCE_MARKER_SCHEMA_VERSION
    assert marker["status"] == "corrupt"
    assert marker["error_code"] == "flow_attempt_provenance_schema_version_missing"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_evidence_export_marks_corrupt_with_retention_tombstone(
    client,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    seeded, trace_user, trace_token = await _seed_trace_view_flow_run_contract_data(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
        attempt_provenance_json={"llm": {"prompt": "missing version"}},
    )
    purged_attempt_id = uuid4()
    async with db_container() as container:
        session = container.session()
        run_id = UUID(seeded["run_id"])
        flow_id = UUID(seeded["flow_id"])
        purged_step_row = (
            await session.execute(
                sa.select(FlowStepResults.step_id, FlowStepResults.step_order)
                .where(FlowStepResults.flow_run_id == run_id)
                .where(FlowStepResults.flow_id == flow_id)
                .order_by(FlowStepResults.step_order.asc())
            )
        ).first()
        assert purged_step_row is not None
        purged_step_id, purged_step_order = purged_step_row
        now = datetime.now(timezone.utc)
        session.add(
            FlowStepAttempts(
                id=purged_attempt_id,
                flow_run_id=run_id,
                flow_id=flow_id,
                tenant_id=trace_user.tenant_id,
                step_id=purged_step_id,
                step_order=purged_step_order,
                attempt_no=2,
                celery_task_id=None,
                status="completed",
                error_code=None,
                error_message=None,
                requested_model="gpt-4o-mini",
                response_model="gpt-4o-mini",
                provider="openai",
                finish_reason="stop",
                provider_response_id=None,
                num_tokens_input=0,
                num_tokens_output=0,
                provenance_json=_attempt_retention_marker_payload(
                    tenant_id=trace_user.tenant_id,
                    run_id=run_id,
                    trace_id=seeded["trace_id"],
                    object_id=purged_attempt_id,
                ),
                started_at=now,
                finished_at=now,
            )
        )
        await session.flush()

    response = await client.get(
        f"/api/v1/flows/{seeded['flow_id']}/runs/{seeded['run_id']}/evidence/export?format=json",
        headers={"Authorization": f"Bearer {trace_token}"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["manifest"]["provenance_persisted_version_status"] == "corrupt"
    assert payload["manifest"]["retention_state_summary"]["tombstone_count"] == 1
    assert payload["manifest"]["retention_state_summary"]["retention_purged_count"] == 1
    assert (
        payload["summary"]["rag_usage_tracking"]["tracking_state"] == "unknown_corrupt"
    )
    assert (
        payload["summary"]["rag_usage_tracking"]["retention_purged_attempt_count"] == 1
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_evidence_fails_closed_when_audit_logging_is_unavailable(
    client,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    seeded, _, trace_token = await _seed_trace_view_flow_run_contract_data(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
    )
    audit_service = type("FailingAuditService", (), {})()

    async def _raise(*args, **kwargs):
        raise RuntimeError("audit down")

    audit_service.log_async = _raise

    Container.audit_service.override(providers.Object(audit_service))
    try:
        response = await client.get(
            f"/api/v1/flows/{seeded['flow_id']}/runs/{seeded['run_id']}/evidence/",
            headers={"Authorization": f"Bearer {trace_token}"},
        )
    finally:
        Container.audit_service.reset_last_overriding()

    assert response.status_code == 503, response.text
    payload = response.json()
    assert payload["code"] == "flow_evidence_audit_logging_failed"
    assert payload["context"]["audit_required"] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_evidence_export_fails_closed_when_audit_logging_is_unavailable(
    client,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    seeded, _, trace_token = await _seed_trace_view_flow_run_contract_data(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
    )
    audit_service = type("FailingAuditService", (), {})()

    async def _raise(*args, **kwargs):
        raise RuntimeError("audit down")

    audit_service.log_async = _raise

    Container.audit_service.override(providers.Object(audit_service))
    try:
        response = await client.get(
            f"/api/v1/flows/{seeded['flow_id']}/runs/{seeded['run_id']}/evidence/export?format=json",
            headers={"Authorization": f"Bearer {trace_token}"},
        )
    finally:
        Container.audit_service.reset_last_overriding()

    assert response.status_code == 503, response.text
    payload = response.json()
    assert payload["code"] == "flow_evidence_audit_logging_failed"
    assert payload["context"]["audit_required"] is True
