from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers

from intric.database.tables.flow_tables import (
    FlowRuns,
    FlowStepAttempts,
    FlowStepResults,
)
from intric.database.tables.roles_table import Roles
from intric.database.tables.users_table import users_roles_table
from intric.flows import (
    Flow,
    FlowFactory,
    FlowRepository,
    FlowStep,
    FlowVersionRepository,
)
from intric.main.container.container import Container
from intric.roles.permissions import Permission
from intric.spaces.api.space_models import SpaceRoleValue
from intric.users.user import UserAdd, UserState


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
                mcp_policy="inherit",
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


async def _create_view_only_user_and_token(
    *, db_container, patch_auth_service_jwt, tenant_id: UUID
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
            name=f"Flow Viewer {uuid4().hex[:8]}",
            permissions=[Permission.FLOWS_VIEW.value],
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

        flow_repo = FlowRepository(session=session, factory=FlowFactory())
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
        flow = flow.model_copy(update={"published_version": 1})
        flow = await flow_repo.update(flow=flow, tenant_id=admin_user.tenant_id)

        step = flow.steps[0]
        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_checksum="evidence-contract-checksum",
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

        started_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        finished_at = datetime.now(timezone.utc)
        run = FlowRuns(
            flow_id=flow.id,
            flow_version=1,
            principal_type="user",
            principal_user_id=admin_user.id,
            user_id=admin_user.id,
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

        session.add(
            FlowStepResults(
                flow_run_id=run.id,
                flow_id=flow.id,
                tenant_id=admin_user.tenant_id,
                step_id=step.id,
                step_order=1,
                assistant_id=assistant.id,
                input_payload_json={
                    "question": "What happened?",
                    "token": "super-secret",
                    "diagnostics": [{"code": "ok"}],
                    "runtime_input": {
                        "file_ids": ["input-file-1"],
                        "files_count": 1,
                        "files": [
                            {
                                "id": "input-file-1",
                                "name": "underlag.pdf",
                                "checksum": "input-checksum",
                                "size": 256,
                                "mimetype": "application/pdf",
                                "file_type": "document",
                                "text_length": 42,
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
                tool_calls_metadata=[],
            )
        )
        session.add(
            FlowStepAttempts(
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
                provenance_json={
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
        )
        await session.flush()

        return {
            "flow_id": str(flow.id),
            "run_id": str(run.id),
            "space_id": str(space.id),
            "trace_id": str(run.trace_id),
        }


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
    seeded = await _seed_flow_run_contract_data(
        db_container=db_container,
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
    seeded = await _seed_flow_run_contract_data(
        db_container=db_container,
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
async def test_flow_run_evidence_export_returns_redacted_json_attachment(
    client,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    seeded = await _seed_flow_run_contract_data(
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
    )

    async with db_container() as container:
        auth_service = container.auth_service()
        admin_token = auth_service.create_access_token_for_user(admin_user)

    response = await client.get(
        f"/api/v1/flows/{seeded['flow_id']}/runs/{seeded['run_id']}/evidence/export?format=json",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert "attachment;" in response.headers["content-disposition"]
    payload = response.json()
    assert payload["schema_version"] == "flow-evidence-export.v3"
    assert payload["manifest"]["schema_version"] == payload["schema_version"]
    assert payload["manifest"]["run_id"] == seeded["run_id"]
    assert payload["manifest"]["tenant_id"] == str(admin_user.tenant_id)
    assert payload["manifest"]["trace_id"] == seeded["trace_id"]
    assert payload["manifest"]["content_hash"] == payload["content_hash"]
    assert payload["manifest"]["content_hash_input"] == "redacted"
    assert payload["manifest"]["exported_at"] == payload["generated_at"]
    assert payload["manifest"]["detail_mode"] == "redacted"
    assert payload["manifest"]["export_reason"] == "support_debug"
    assert payload["manifest"]["exported_by_user_id"] == str(admin_user.id)
    assert payload["manifest"]["redaction_applied"] is True
    assert payload["manifest"]["retention_state_summary"]["tracking_state"] == (
        "not_tracked"
    )
    assert payload["manifest"]["artifact_availability_summary"]["tracking_state"] == (
        "payload_derived"
    )
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
async def test_flow_run_evidence_fails_closed_when_audit_logging_is_unavailable(
    client,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    seeded = await _seed_flow_run_contract_data(
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
    )
    audit_service = type("FailingAuditService", (), {})()

    async def _raise(*args, **kwargs):
        raise RuntimeError("audit down")

    audit_service.log_async = _raise

    async with db_container() as container:
        auth_service = container.auth_service()
        admin_token = auth_service.create_access_token_for_user(admin_user)

    Container.audit_service.override(providers.Object(audit_service))
    try:
        response = await client.get(
            f"/api/v1/flows/{seeded['flow_id']}/runs/{seeded['run_id']}/evidence/",
            headers={"Authorization": f"Bearer {admin_token}"},
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
    seeded = await _seed_flow_run_contract_data(
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
    )
    audit_service = type("FailingAuditService", (), {})()

    async def _raise(*args, **kwargs):
        raise RuntimeError("audit down")

    audit_service.log_async = _raise

    async with db_container() as container:
        auth_service = container.auth_service()
        admin_token = auth_service.create_access_token_for_user(admin_user)

    Container.audit_service.override(providers.Object(audit_service))
    try:
        response = await client.get(
            f"/api/v1/flows/{seeded['flow_id']}/runs/{seeded['run_id']}/evidence/export?format=json",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    finally:
        Container.audit_service.reset_last_overriding()

    assert response.status_code == 503, response.text
    payload = response.json()
    assert payload["code"] == "flow_evidence_audit_logging_failed"
    assert payload["context"]["audit_required"] is True
