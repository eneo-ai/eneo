from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.audit.domain.action_types import ActionType
from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
from eneo.database.tables.flow_tables import (
    FlowRunReviewCheckpoints,
    FlowRuns,
    FlowStepAttempts,
    FlowStepResults,
)
from eneo.database.tables.roles_table import Roles
from eneo.database.tables.users_table import users_roles_table
from eneo.files.file_models import FileInfo, FileType
from eneo.flows.api import (
    flow_run_lifecycle_router,
    flow_run_rerun_router,
    flow_run_review_router,
)
from eneo.flows.domain.flow import FlowStepResult
from eneo.flows.enums import FlowRunReviewCheckpointState, FlowStepResultStatus
from eneo.flows.flow_run_input_envelope import FLOW_INPUT_TRANSCRIPTION_KEY
from eneo.flows.flow_run_step_result_file import FlowStepResultFileReference
from eneo.flows.principal import FlowPrincipal
from eneo.main.exceptions import ErrorCodes
from eneo.main.models import GeneralError
from eneo.roles.permissions import Permission


async def _noop_dispatch_flow_run_recoverably_after_commit(
    *, run_id: UUID, tenant_id: UUID, expected_revision: int
) -> None:
    _ = (run_id, tenant_id, expected_revision)


async def _flow_run_first_page_count(client, *, flow_id: str, token: str) -> int:
    response = await client.get(
        f"/api/v1/flows/{flow_id}/runs/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    return response.json()["count"]


def _validation_error_types(payload: dict[str, object], *, request_id: str) -> set[str]:
    error = GeneralError.model_validate(payload)
    assert error.message == "Request validation failed."
    assert error.eneo_error_code == ErrorCodes.VALIDATION_ERROR
    assert error.code == "request_validation_error"
    assert error.request_id == request_id
    details = error.details
    assert isinstance(details, dict)
    errors = details.get("errors")
    assert isinstance(errors, list)
    error_types: set[str] = set()
    for item in errors:
        if not isinstance(item, dict):
            continue
        error_type = item.get("type")
        if isinstance(error_type, str):
            error_types.add(error_type)
    return error_types


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    _ = patch_auth_service_jwt
    async with db_container() as container:
        session = container.session()
        user_repo = container.user_repo()
        auth_service = container.auth_service()

        role = Roles(
            name=f"Flow Consumer Test {uuid4().hex[:8]}",
            permissions=[
                Permission.FLOWS_MANAGE.value,
                Permission.FLOWS_RUN.value,
                Permission.FLOWS_TRACE.value,
            ],
            tenant_id=admin_user.tenant_id,
        )
        session.add(role)
        await session.flush()
        await session.execute(
            sa.insert(users_roles_table).values(user_id=admin_user.id, role_id=role.id)
        )
        await session.flush()

        refreshed_user = await user_repo.get_user_by_email(admin_user.email)
        return auth_service.create_access_token_for_user(refreshed_user)


async def _create_space(client, *, token: str) -> str:
    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"flow-consumer-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_flow_service_key(
    client,
    *,
    token: str,
    scope_type: str = "tenant",
    scope_id: str | None = None,
    permission: str = "write",
    resource_permissions: dict[str, str] | None = None,
) -> str:
    expires_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    payload: dict[str, object] = {
        "name": f"flow-service-key-{uuid4().hex[:8]}",
        "key_type": "sk_",
        "permission": permission,
        "scope_type": scope_type,
        "ownership": "service",
        "expires_at": expires_at,
        "resource_permissions": resource_permissions or {"flows": "write"},
    }
    if scope_id is not None:
        payload["scope_id"] = scope_id
    response = await client.post(
        "/api/v1/api-keys",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["secret"]


async def _create_published_flow(
    client,
    *,
    token: str,
    space_id: str,
    review_output_contract: dict[str, object] | None = None,
    output_mode: str = "pass_through",
    output_type: str = "json",
    output_contract: dict[str, object] | None = None,
    output_config: dict[str, object] | None = None,
) -> dict:
    create_response = await client.post(
        "/api/v1/flows/",
        json={
            "space_id": space_id,
            "name": f"consumer-flow-{uuid4().hex[:8]}",
            "description": "Runtime API consumer contract flow",
            "steps": [],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_response.status_code == 201, create_response.text
    flow_id = create_response.json()["id"]

    assistant_response = await client.post(
        f"/api/v1/flows/{flow_id}/assistants/",
        json={"name": f"consumer-assistant-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert assistant_response.status_code == 201, assistant_response.text
    assistant_id = assistant_response.json()["id"]

    step_payload = {
        "assistant_id": assistant_id,
        "step_order": 1,
        "user_description": "Produce the consumer-visible result",
        "input_source": "flow_input",
        "input_type": "text",
        "output_mode": output_mode,
        "output_type": output_type,
    }
    if output_contract is not None:
        step_payload["output_contract"] = output_contract
    if output_config is not None:
        step_payload["output_config"] = output_config
    if review_output_contract is not None:
        step_payload["review_policy"] = {"mode": "view"}
        step_payload["output_contract"] = review_output_contract

    update_response = await client.patch(
        f"/api/v1/flows/{flow_id}/",
        json={
            "name": f"Consumer API Flow {flow_id[:8]}",
            "description": "Runtime API consumer contract flow",
            "steps": [step_payload],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert update_response.status_code == 200, update_response.text
    flow = update_response.json()

    publish_response = await client.post(
        f"/api/v1/flows/{flow_id}/publish/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert publish_response.status_code == 200, publish_response.text
    flow["published_version"] = publish_response.json()["published_version"]
    return flow


async def _create_published_required_runtime_input_flow(
    client, *, token: str, space_id: str
) -> dict:
    create_response = await client.post(
        "/api/v1/flows/",
        json={
            "space_id": space_id,
            "name": f"required-runtime-input-flow-{uuid4().hex[:8]}",
            "description": "Runtime input required API contract flow",
            "steps": [],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_response.status_code == 201, create_response.text
    flow_id = create_response.json()["id"]

    assistant_response = await client.post(
        f"/api/v1/flows/{flow_id}/assistants/",
        json={"name": f"required-runtime-input-assistant-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert assistant_response.status_code == 201, assistant_response.text
    assistant_id = assistant_response.json()["id"]

    update_response = await client.patch(
        f"/api/v1/flows/{flow_id}/",
        json={
            "name": f"Required Runtime Input Flow {uuid4().hex[:8]}",
            "description": "Runtime input required API contract flow",
            "steps": [
                {
                    "assistant_id": assistant_id,
                    "step_order": 1,
                    "user_description": "Use the uploaded document to produce a result",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "input_config": {
                        "runtime_input": {
                            "enabled": True,
                            "required": True,
                            "max_files": 1,
                            "input_format": "document",
                            "label": "Source document",
                            "description": "Upload the source document before starting the run.",
                        }
                    },
                    "output_mode": "pass_through",
                    "output_type": "json",
                }
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert update_response.status_code == 200, update_response.text
    flow = update_response.json()

    publish_response = await client.post(
        f"/api/v1/flows/{flow_id}/publish/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert publish_response.status_code == 200, publish_response.text
    flow["published_version"] = publish_response.json()["published_version"]
    return flow


async def _upload_runtime_document(
    client,
    *,
    flow_id: str,
    step_id: str,
    headers: dict[str, str],
) -> dict:
    response = await client.post(
        f"/api/v1/flows/{flow_id}/steps/{step_id}/runtime-files/",
        files={
            "upload_file": (
                "source.txt",
                b"Runtime source document for the flow.",
                "text/plain",
            )
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _mark_first_step_completed(
    *,
    db_container,
    run_id: str,
    flow_id: str,
    tenant_id: str,
) -> None:
    async with db_container() as container:
        session = container.session()
        completed_at = datetime.now(timezone.utc)
        completed_result = await session.execute(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == UUID(run_id))
            .where(FlowStepResults.flow_id == UUID(flow_id))
            .where(FlowStepResults.tenant_id == UUID(tenant_id))
            .where(FlowStepResults.step_order == 1)
            .values(
                status="completed",
                input_payload_json={"text": "hello"},
                output_payload_json={"answer": "consumer-visible"},
                num_tokens_input=3,
                num_tokens_output=5,
            )
            .returning(FlowStepResults.step_id, FlowStepResults.step_order)
        )
        step_id, step_order = completed_result.one()
        session.add(
            FlowStepAttempts(
                flow_run_id=UUID(run_id),
                flow_id=UUID(flow_id),
                tenant_id=UUID(tenant_id),
                step_id=step_id,
                step_order=step_order,
                attempt_no=1,
                status="completed",
                requested_model="gpt-4o-mini",
                response_model="gpt-4o-mini",
                provider="openai",
                finish_reason="stop",
                provider_response_id=f"consumer-runtime-{run_id}",
                num_tokens_input=3,
                num_tokens_output=5,
                input_payload_json={"text": "hello"},
                output_payload_json={"answer": "consumer-visible"},
                started_at=completed_at,
                finished_at=completed_at,
            )
        )


async def _mark_run_completed(
    *,
    db_container,
    run_id: str,
    output_payload_json: dict[str, object] | None = None,
) -> None:
    terminal_payload = (
        output_payload_json
        if output_payload_json is not None
        else {
            "text": '{"answer":"consumer-visible"}',
            "structured": {"answer": "consumer-visible"},
        }
    )
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == UUID(run_id))
            .values(
                status="completed",
                output_payload_json=terminal_payload,
            )
        )


async def _mark_run_completed_with_artifact(
    *,
    db_container,
    run: dict,
    flow: dict,
) -> UUID:
    step = flow["steps"][-1]
    now = datetime.now(timezone.utc)
    async with db_container() as container:
        session = container.session()
        run_row = await session.get(FlowRuns, UUID(run["id"]))
        assert run_row is not None
        principal = FlowPrincipal.from_run(run_row)
        file_service = container.file_service(
            user=None,
            owner=principal.file_owner(tenant_id=run_row.tenant_id),
        )
        artifact = await file_service.save_generated_file(
            payload=b"representative-pdf",
            name="consumer-report.pdf",
            mimetype="application/pdf",
            file_type=FileType.DOCUMENT,
        )

        run_repo = container.flow_run_repo()
        await run_repo.create_or_get_attempt_started(
            run_id=run_row.id,
            flow_id=run_row.flow_id,
            tenant_id=run_row.tenant_id,
            step_id=UUID(step["id"]),
            step_order=int(step["step_order"]),
            attempt_no=1,
            celery_task_id=f"consumer-artifact-{run['id']}",
        )
        result = FlowStepResult(
            id=uuid4(),
            flow_run_id=run_row.id,
            flow_id=run_row.flow_id,
            tenant_id=run_row.tenant_id,
            step_id=UUID(step["id"]),
            step_order=int(step["step_order"]),
            assistant_id=UUID(step["assistant_id"]),
            input_payload_json={"text": "create report"},
            effective_prompt="Create the report",
            output_payload_json=None,
            model_parameters_json=None,
            num_tokens_input=2,
            num_tokens_output=4,
            status=FlowStepResultStatus.COMPLETED,
            error_message=None,
            flow_step_execution_hash="consumer-artifact-step",
            created_at=now,
            updated_at=now,
        )
        persisted = await run_repo.save_step_result(
            run_row.id,
            result,
            tenant_id=run_row.tenant_id,
            attempt_no=1,
            result_file_references=(
                FlowStepResultFileReference(
                    file_id=artifact.id,
                    source="generated_output",
                ),
            ),
        )
        assert persisted is not None
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_row.id)
            .values(status="completed", output_payload_json=None)
        )
        return artifact.id


async def _mark_run_completed_with_file_backed_text(
    *,
    db_container,
    run: dict,
    flow: dict,
) -> tuple[UUID, UUID, UUID]:
    step = flow["steps"][-1]
    now = datetime.now(timezone.utc)
    async with db_container() as container:
        session = container.session()
        run_row = await session.get(FlowRuns, UUID(run["id"]))
        assert run_row is not None
        principal = FlowPrincipal.from_run(run_row)
        file_service = container.file_service(
            user=None,
            owner=principal.file_owner(tenant_id=run_row.tenant_id),
        )

        async def output_file(name: str, text: str) -> FileInfo:
            return await file_service.save_generated_file(
                payload=text.encode("utf-8"),
                name=name,
                mimetype="text/plain",
                file_type=FileType.TEXT,
            )

        historical = await output_file(
            "historical-output.txt", "historical complete text"
        )
        current = await output_file(
            "current-output.txt", "current complete terminal text"
        )
        declared = await output_file("declared-artifact.txt", "declared artifact")

        run_repo = container.flow_run_repo()
        step_id = UUID(step["id"])

        def step_result(output_payload_json: dict[str, object]) -> FlowStepResult:
            return FlowStepResult(
                id=uuid4(),
                flow_run_id=run_row.id,
                flow_id=run_row.flow_id,
                tenant_id=run_row.tenant_id,
                step_id=step_id,
                step_order=int(step["step_order"]),
                assistant_id=UUID(step["assistant_id"]),
                input_payload_json={"text": "produce complete text"},
                effective_prompt="Produce complete text",
                output_payload_json=output_payload_json,
                model_parameters_json=None,
                num_tokens_input=2,
                num_tokens_output=4,
                status=FlowStepResultStatus.COMPLETED,
                error_message=None,
                flow_step_execution_hash="consumer-file-backed-text",
                created_at=now,
                updated_at=now,
            )

        await run_repo.create_or_get_attempt_started(
            run_id=run_row.id,
            flow_id=run_row.flow_id,
            tenant_id=run_row.tenant_id,
            step_id=step_id,
            step_order=int(step["step_order"]),
            attempt_no=1,
            celery_task_id=f"consumer-text-history-{run['id']}",
        )
        historical_result = step_result({"text": "historical complete text"})
        assert (
            await run_repo.save_step_result(
                run_row.id,
                historical_result,
                tenant_id=run_row.tenant_id,
                attempt_no=1,
                result_file_references=(
                    FlowStepResultFileReference(
                        file_id=historical.id,
                        source="generated_output",
                    ),
                ),
            )
            is not None
        )

        await run_repo.create_or_get_attempt_started(
            run_id=run_row.id,
            flow_id=run_row.flow_id,
            tenant_id=run_row.tenant_id,
            step_id=step_id,
            step_order=int(step["step_order"]),
            attempt_no=2,
            celery_task_id=f"consumer-text-current-{run['id']}",
        )
        terminal_payload = {
            "text": "current",
            "text_overflow": {
                "generated_file_ids": [str(current.id)],
                "inline_text_bytes": 7,
                "full_text_bytes": len(
                    "current complete terminal text".encode("utf-8")
                ),
            },
        }
        current_result = step_result(terminal_payload)
        assert (
            await run_repo.save_step_result(
                run_row.id,
                current_result,
                tenant_id=run_row.tenant_id,
                attempt_no=2,
                result_file_references=(
                    FlowStepResultFileReference(
                        file_id=current.id,
                        source="generated_output",
                    ),
                    FlowStepResultFileReference(
                        file_id=declared.id,
                        source="declared_artifact",
                    ),
                ),
            )
            is not None
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_row.id)
            .values(status="completed", output_payload_json=terminal_payload)
        )
        return current.id, historical.id, declared.id


async def _create_completed_runtime_input_run(
    *,
    client,
    db_container,
    admin_token: str,
) -> tuple[dict, dict, str, dict]:
    space_id = await _create_space(client, token=admin_token)
    flow = await _create_published_required_runtime_input_flow(
        client,
        token=admin_token,
        space_id=space_id,
    )
    flow_id = flow["id"]

    contract_response = await client.get(
        f"/api/v1/flows/{flow_id}/run-contract/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert contract_response.status_code == 200, contract_response.text
    step_id = contract_response.json()["steps_requiring_input"][0]["step_id"]
    uploaded = await _upload_runtime_document(
        client,
        flow_id=flow_id,
        step_id=step_id,
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    run_response = await client.post(
        f"/api/v1/flows/{flow_id}/runs/",
        json={
            "expected_flow_version": flow["published_version"],
            "input_payload_json": {"text": "hello"},
            "step_inputs": {step_id: {"file_ids": [uploaded["id"]]}},
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert run_response.status_code == 201, run_response.text
    run = run_response.json()

    await _mark_first_step_completed(
        db_container=db_container,
        run_id=run["id"],
        flow_id=flow_id,
        tenant_id=run["tenant_id"],
    )
    await _mark_run_completed(db_container=db_container, run_id=run["id"])
    return flow, run, step_id, uploaded


async def _open_first_step_review_checkpoint(
    *,
    db_container,
    run: dict,
    flow: dict,
    output_contract: dict[str, object],
    current_payload_json: dict[str, object],
) -> str:
    step = flow["steps"][0]
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == UUID(run["id"]))
            .values(status="awaiting_review")
        )
        run_row = await session.get(FlowRuns, UUID(run["id"]))
        assert run_row is not None
        requester_user_id = (
            run_row.principal_user_id if run_row.principal_type == "user" else None
        )
        requester_service_id = (
            run_row.principal_service_id
            if run_row.principal_type == "service_key"
            else None
        )
        await session.execute(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == UUID(run["id"]))
            .where(FlowStepResults.step_id == UUID(step["id"]))
            .values(
                status="completed",
                input_payload_json={"text": "hello"},
                output_payload_json=current_payload_json,
                num_tokens_input=3,
                num_tokens_output=5,
            )
        )
        completed_at = datetime.now(timezone.utc)
        session.add(
            FlowStepAttempts(
                flow_run_id=UUID(run["id"]),
                flow_id=UUID(flow["id"]),
                tenant_id=UUID(run["tenant_id"]),
                step_id=UUID(step["id"]),
                step_order=1,
                attempt_no=1,
                status="completed",
                requested_model="gpt-4o-mini",
                response_model="gpt-4o-mini",
                provider="openai",
                finish_reason="stop",
                provider_response_id=f"consumer-review-{run['id']}",
                num_tokens_input=3,
                num_tokens_output=5,
                started_at=completed_at,
                finished_at=completed_at,
            )
        )
        await session.flush()
        checkpoint = FlowRunReviewCheckpoints(
            tenant_id=UUID(run["tenant_id"]),
            flow_id=UUID(flow["id"]),
            flow_run_id=UUID(run["id"]),
            step_id=UUID(step["id"]),
            step_order=1,
            attempt_no=1,
            state=FlowRunReviewCheckpointState.AWAITING_REVIEW.value,
            revision=1,
            schema_version=1,
            original_payload_json=current_payload_json,
            current_payload_json=current_payload_json,
            step_label=step["user_description"],
            review_mode="view",
            output_type="json",
            output_contract_json=output_contract,
            requester_principal_type=run_row.principal_type,
            requester_user_id=requester_user_id,
            requester_service_id=requester_service_id,
        )
        session.add(checkpoint)
        await session.flush()
        return str(checkpoint.id)


def _runtime_path(
    template: str,
    *,
    run_id: str,
    checkpoint_id: str | None = None,
) -> str:
    path = template.replace("{run_id}", run_id)
    if checkpoint_id is not None:
        path = path.replace("{checkpoint_id}", checkpoint_id)
    assert "{" not in path
    return path


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_flows_scope_mismatch_returns_general_error(
    client,
    admin_token,
):
    requested_space_id = await _create_space(client, token=admin_token)
    key_space_id = await _create_space(client, token=admin_token)
    service_key = await _create_flow_service_key(
        client,
        token=admin_token,
        scope_type="space",
        scope_id=key_space_id,
    )

    response = await client.get(
        "/api/v1/flows/",
        params={"space_id": requested_space_id},
        headers={
            "X-API-Key": service_key,
            "X-Correlation-ID": "flow-scope-mismatch-test",
        },
    )

    assert response.status_code == 403, response.text
    error = GeneralError.model_validate(response.json())
    assert error.message == "API key space scope does not match requested space."
    assert error.eneo_error_code == ErrorCodes.UNAUTHORIZED
    assert error.code == "insufficient_scope"
    assert error.context == {"auth_layer": "api_key_scope"}
    assert error.request_id == "flow-scope-mismatch-test"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_service_key_evidence_permission_matrix(
    client,
    admin_token,
    monkeypatch,
):
    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        _noop_dispatch_flow_run_recoverably_after_commit,
    )

    space_id = await _create_space(client, token=admin_token)
    flow = await _create_published_flow(client, token=admin_token, space_id=space_id)
    published_response = await client.get(
        f"/api/v1/flows/{flow['id']}/published/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert published_response.status_code == 200, published_response.text
    runtime_paths = published_response.json()["runtime_paths"]

    evidence_only_key = await _create_flow_service_key(
        client,
        token=admin_token,
        permission="read",
        resource_permissions={"flow_evidence": "read"},
    )
    flows_only_key = await _create_flow_service_key(
        client,
        token=admin_token,
        resource_permissions={"flows": "write"},
    )
    evidence_view_key = await _create_flow_service_key(
        client,
        token=admin_token,
        resource_permissions={"flows": "write", "flow_evidence": "read"},
    )

    async def create_service_run(service_key: str, *, text: str) -> dict:
        response = await client.post(
            runtime_paths["create_run"],
            json={
                "expected_flow_version": flow["published_version"],
                "input_payload_json": {"text": text},
            },
            headers={
                "X-API-Key": service_key,
                "Idempotency-Key": f"service-evidence-contract:{uuid4().hex}",
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    flows_only_run = await create_service_run(
        flows_only_key,
        text="created by flows-only key",
    )
    evidence_view_run = await create_service_run(
        evidence_view_key,
        text="created by evidence-view key",
    )
    flows_only_evidence_path = _runtime_path(
        runtime_paths["evidence_template"],
        run_id=flows_only_run["id"],
    )
    evidence_view_path = _runtime_path(
        runtime_paths["evidence_template"],
        run_id=evidence_view_run["id"],
    )

    evidence_only_response = await client.get(
        evidence_view_path,
        headers={"X-API-Key": evidence_only_key},
    )
    assert evidence_only_response.status_code == 403, evidence_only_response.text
    assert evidence_only_response.json()["code"] == "insufficient_resource_permission"

    flows_only_response = await client.get(
        flows_only_evidence_path,
        headers={"X-API-Key": flows_only_key},
    )
    assert flows_only_response.status_code == 403, flows_only_response.text
    assert flows_only_response.json()["code"] == "flow_run_evidence_forbidden"

    evidence_view_response = await client.get(
        evidence_view_path,
        headers={"X-API-Key": evidence_view_key},
    )
    assert evidence_view_response.status_code == 200, evidence_view_response.text
    assert evidence_view_response.json()["run"]["id"] == evidence_view_run["id"]

    redacted_export_response = await client.get(
        f"{evidence_view_path.rstrip('/')}/export",
        headers={"X-API-Key": evidence_view_key},
    )
    assert redacted_export_response.status_code == 403, redacted_export_response.text
    assert redacted_export_response.json()["code"] == "flow_run_evidence_forbidden"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_consumer_runtime_routes_support_start_replay_poll_and_steps(
    client,
    db_container,
    admin_token,
    monkeypatch,
):
    dispatch_requests: list[tuple[UUID, UUID, int]] = []

    async def _record_dispatch(
        *, run_id: UUID, tenant_id: UUID, expected_revision: int
    ) -> None:
        dispatch_requests.append((run_id, tenant_id, expected_revision))

    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        _record_dispatch,
    )

    space_id = await _create_space(client, token=admin_token)
    flow = await _create_published_flow(client, token=admin_token, space_id=space_id)
    flow_id = flow["id"]

    published_response = await client.get(
        f"/api/v1/flows/{flow_id}/published/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert published_response.status_code == 200, published_response.text
    published_payload = published_response.json()
    assert published_payload["id"] == flow_id

    status_capabilities_response = await client.get(
        "/api/v1/flows/runs/status-capabilities/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert status_capabilities_response.status_code == 200, (
        status_capabilities_response.text
    )
    rerun_eligibility = {
        row["status"]: row["is_rerun_eligible"]
        for row in status_capabilities_response.json()["statuses"]
    }
    assert rerun_eligibility == {
        "queued": False,
        "running": False,
        "awaiting_review": False,
        "completed": True,
        "failed": True,
        "cancelled": False,
    }

    assert published_payload["runtime_paths"]["create_run"].endswith(
        f"/flows/{flow_id}/runs/"
    )
    review_paths = published_payload["runtime_paths"]["review_checkpoints"]
    assert review_paths["active_template"].endswith(
        f"/flows/{flow_id}/runs/{{run_id}}/review-checkpoints/active/"
    )
    assert review_paths["edit_template"].endswith(
        f"/flows/{flow_id}/runs/{{run_id}}/review-checkpoints/{{checkpoint_id}}/"
    )
    assert review_paths["approve_template"].endswith(
        f"/flows/{flow_id}/runs/{{run_id}}/review-checkpoints/"
        "{checkpoint_id}/approve/"
    )
    assert review_paths["reject_template"].endswith(
        f"/flows/{flow_id}/runs/{{run_id}}/review-checkpoints/{{checkpoint_id}}/reject/"
    )
    assert review_paths["resume_template"].endswith(
        f"/flows/{flow_id}/runs/{{run_id}}/review-checkpoints/{{checkpoint_id}}/resume/"
    )

    run_payload = {
        "expected_flow_version": flow["published_version"],
        "input_payload_json": {"text": "hello"},
        "step_inputs": {},
    }
    idempotency_key = f"flow-run:{uuid4().hex}"
    first_run_response = await client.post(
        f"/api/v1/flows/{flow_id}/runs/",
        json=run_payload,
        headers={
            "Authorization": f"Bearer {admin_token}",
            "Idempotency-Key": idempotency_key,
        },
    )
    assert first_run_response.status_code == 201, first_run_response.text
    first_run = first_run_response.json()
    assert first_run["input_payload_json"] == {"text": "hello"}
    assert [request[0] for request in dispatch_requests] == [UUID(first_run["id"])]

    immediate_poll_response = await client.get(
        published_payload["runtime_paths"]["get_run_template"].replace(
            "{run_id}", first_run["id"]
        ),
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert immediate_poll_response.status_code == 200, immediate_poll_response.text
    immediate_poll = immediate_poll_response.json()
    assert immediate_poll["id"] == first_run["id"]
    assert immediate_poll["input_payload_json"] == {"text": "hello"}
    assert immediate_poll["result"] is None

    replay_response = await client.post(
        f"/api/v1/flows/{flow_id}/runs/",
        json=run_payload,
        headers={
            "Authorization": f"Bearer {admin_token}",
            "Idempotency-Key": idempotency_key,
        },
    )
    assert replay_response.status_code == 201, replay_response.text
    assert replay_response.json()["id"] == first_run["id"]
    assert [request[0] for request in dispatch_requests] == [UUID(first_run["id"])]

    conflict_response = await client.post(
        f"/api/v1/flows/{flow_id}/runs/",
        json={
            **run_payload,
            "input_payload_json": {"text": "different"},
        },
        headers={
            "Authorization": f"Bearer {admin_token}",
            "Idempotency-Key": idempotency_key,
        },
    )
    assert conflict_response.status_code == 400, conflict_response.text
    assert conflict_response.json()["code"] == "flow_run_idempotency_conflict"

    second_run_response = await client.post(
        f"/api/v1/flows/{flow_id}/runs/",
        json={
            "expected_flow_version": flow["published_version"],
            "input_payload_json": {"text": "second"},
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert second_run_response.status_code == 201, second_run_response.text
    second_run = second_run_response.json()
    assert [request[0] for request in dispatch_requests] == [
        UUID(first_run["id"]),
        UUID(second_run["id"]),
    ]

    list_response = await client.get(
        f"/api/v1/flows/{flow_id}/runs/?limit=1&offset=0",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert list_response.status_code == 200, list_response.text
    list_payload = list_response.json()
    assert list_payload["count"] == 1
    assert len(list_payload["items"]) == 1
    assert list_payload["has_more"] is True

    poll_response = await client.get(
        f"/api/v1/flows/{flow_id}/runs/{first_run['id']}/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert poll_response.status_code == 200, poll_response.text
    assert poll_response.json()["id"] == first_run["id"]
    assert poll_response.json()["flow_id"] == flow_id

    await _mark_first_step_completed(
        db_container=db_container,
        run_id=first_run["id"],
        flow_id=flow_id,
        tenant_id=first_run["tenant_id"],
    )
    steps_response = await client.get(
        f"/api/v1/flows/{flow_id}/runs/{first_run['id']}/steps/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert steps_response.status_code == 200, steps_response.text
    steps = steps_response.json()
    assert len(steps) == 1
    assert steps[0]["status"] == "completed"
    assert steps[0]["output_payload_json"] == {"answer": "consumer-visible"}

    await _mark_run_completed(
        db_container=db_container,
        run_id=first_run["id"],
        output_payload_json={
            "text": '{"answer":"consumer-visible"}',
            "structured": {"answer": "consumer-visible"},
        },
    )

    completed_runs_response = await client.get(
        f"/api/v1/flows/{flow_id}/runs/?status=completed",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert completed_runs_response.status_code == 200, completed_runs_response.text
    completed_runs = completed_runs_response.json()["items"]
    assert [run["id"] for run in completed_runs] == [first_run["id"]]
    assert completed_runs[0]["result"] == {
        "kind": "structured",
        "value": {"answer": "consumer-visible"},
        "output_contract": None,
    }
    completed_replay_response = await client.post(
        f"/api/v1/flows/{flow_id}/runs/",
        json=run_payload,
        headers={
            "Authorization": f"Bearer {admin_token}",
            "Idempotency-Key": idempotency_key,
        },
    )
    assert completed_replay_response.status_code == 201, completed_replay_response.text
    assert completed_replay_response.json()["result"] == completed_runs[0]["result"]

    completed_cancel_response = await client.post(
        f"/api/v1/flows/{flow_id}/runs/{first_run['id']}/cancel/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert completed_cancel_response.status_code == 200, completed_cancel_response.text
    assert completed_cancel_response.json()["status"] == "completed"
    assert completed_cancel_response.json()["result"] == completed_runs[0]["result"]

    queued_runs_response = await client.get(
        f"/api/v1/flows/{flow_id}/runs/?status=queued",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert queued_runs_response.status_code == 200, queued_runs_response.text
    queued_runs = queued_runs_response.json()["items"]
    assert [run["id"] for run in queued_runs] == [second_run["id"]]

    active_or_done_runs_response = await client.get(
        f"/api/v1/flows/{flow_id}/runs/?status=completed&status=queued",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert active_or_done_runs_response.status_code == 200, (
        active_or_done_runs_response.text
    )
    active_or_done_run_ids = {
        run["id"] for run in active_or_done_runs_response.json()["items"]
    }
    assert active_or_done_run_ids == {first_run["id"], second_run["id"]}

    evidence_response = await client.get(
        published_payload["runtime_paths"]["evidence_template"].replace(
            "{run_id}",
            first_run["id"],
        ),
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert evidence_response.status_code == 200, evidence_response.text
    evidence = evidence_response.json()
    assert evidence["run"]["id"] == first_run["id"]
    assert evidence["step_results"][0]["output_payload_json"] == {
        "answer": "consumer-visible"
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_create_concurrency_limit_preserves_creation_side_effects(
    client,
    db_container,
    admin_token,
    monkeypatch,
):
    dispatch_requests: list[tuple[UUID, UUID, int]] = []

    async def _record_dispatch(
        *, run_id: UUID, tenant_id: UUID, expected_revision: int
    ) -> None:
        dispatch_requests.append((run_id, tenant_id, expected_revision))

    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        _record_dispatch,
    )
    space_id = await _create_space(client, token=admin_token)
    flow = await _create_published_flow(client, token=admin_token, space_id=space_id)
    flow_id = flow["id"]
    tenant_id: str | None = None

    for index in range(4):
        response = await client.post(
            f"/api/v1/flows/{flow_id}/runs/",
            json={
                "expected_flow_version": flow["published_version"],
                "input_payload_json": {"index": index},
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 201, response.text
        tenant_id = response.json()["tenant_id"]

    assert tenant_id is not None
    async with db_container() as container:
        session = container.session()
        run_count_before = await session.scalar(
            sa.select(sa.func.count(FlowRuns.id)).where(
                FlowRuns.flow_id == UUID(flow_id),
                FlowRuns.tenant_id == UUID(tenant_id),
            )
        )
        audit_count_before = await session.scalar(
            sa.select(sa.func.count(AuditLogTable.id)).where(
                AuditLogTable.tenant_id == UUID(tenant_id),
                AuditLogTable.action == ActionType.FLOW_RUN_CREATED.value,
            )
        )

    response = await client.post(
        f"/api/v1/flows/{flow_id}/runs/",
        json={
            "expected_flow_version": flow["published_version"],
            "input_payload_json": {"index": 4},
        },
        headers={
            "Authorization": f"Bearer {admin_token}",
            "x-request-id": "flow-run-concurrency-limit-test",
        },
    )

    assert response.status_code == 429, response.text
    assert response.headers["Retry-After"] == "60"
    error = GeneralError.model_validate(response.json())
    assert error.code == "flow_run_concurrency_limit_reached"
    assert response.json() == {
        "message": "Concurrent flow run limit reached for this tenant.",
        "eneo_error_code": 9007,
        "code": "flow_run_concurrency_limit_reached",
        "context": {"max_concurrent_runs": 4, "retry_after_seconds": 60},
        "request_id": "flow-run-concurrency-limit-test",
    }
    async with db_container() as container:
        session = container.session()
        run_count_after = await session.scalar(
            sa.select(sa.func.count(FlowRuns.id)).where(
                FlowRuns.flow_id == UUID(flow_id),
                FlowRuns.tenant_id == UUID(tenant_id),
            )
        )
        audit_count_after = await session.scalar(
            sa.select(sa.func.count(AuditLogTable.id)).where(
                AuditLogTable.tenant_id == UUID(tenant_id),
                AuditLogTable.action == ActionType.FLOW_RUN_CREATED.value,
            )
        )

    assert run_count_before == run_count_after == 4
    assert audit_count_before == audit_count_after
    assert len(dispatch_requests) == 4


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_public_projects_text_artifact_and_outbound_results(
    client,
    db_container,
    admin_token,
    monkeypatch,
):
    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        _noop_dispatch_flow_run_recoverably_after_commit,
    )
    space_id = await _create_space(client, token=admin_token)
    text_flow = await _create_published_flow(
        client,
        token=admin_token,
        space_id=space_id,
        output_type="text",
    )
    artifact_flow = await _create_published_flow(
        client,
        token=admin_token,
        space_id=space_id,
        output_mode="render_verbatim",
        output_type="pdf",
    )
    outbound_flow = await _create_published_flow(
        client,
        token=admin_token,
        space_id=space_id,
        output_mode="http_post",
        output_type="json",
        output_config={
            "url": "https://example.org/hook",
            "auth": {"mode": "none"},
            "timeout_seconds": 25,
            "body": {
                "mode": "text_template",
                "template": '{"message":"{{flow_input.text}}"}',
            },
        },
    )

    async def create_run(flow: dict) -> dict:
        response = await client.post(
            f"/api/v1/flows/{flow['id']}/runs/",
            json={
                "expected_flow_version": flow["published_version"],
                "input_payload_json": {"text": "produce result"},
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 201, response.text
        return response.json()

    text_run = await create_run(text_flow)
    artifact_run = await create_run(artifact_flow)
    outbound_run = await create_run(outbound_flow)
    await _mark_run_completed(
        db_container=db_container,
        run_id=text_run["id"],
        output_payload_json={"text": "Finished public report"},
    )
    artifact_file_id = await _mark_run_completed_with_artifact(
        db_container=db_container,
        run=artifact_run,
        flow=artifact_flow,
    )
    await _mark_run_completed(
        db_container=db_container,
        run_id=outbound_run["id"],
        output_payload_json={},
    )

    async def poll(flow: dict, run: dict) -> dict:
        response = await client.get(
            f"/api/v1/flows/{flow['id']}/runs/{run['id']}/",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200, response.text
        return response.json()

    text_public = await poll(text_flow, text_run)
    artifact_public = await poll(artifact_flow, artifact_run)
    outbound_public = await poll(outbound_flow, outbound_run)

    assert text_public["result"] == {
        "kind": "inline_text",
        "text": "Finished public report",
    }
    assert "output_payload_json" not in text_public
    assert artifact_public["result"]["kind"] == "artifact"
    assert [item["file_id"] for item in artifact_public["result"]["files"]] == [
        str(artifact_file_id)
    ]
    assert artifact_public["result"]["files"] == artifact_public["result_files"]
    signed_url_response = await client.post(
        (
            f"/api/v1/flows/{artifact_flow['id']}/runs/{artifact_run['id']}"
            f"/artifacts/{artifact_file_id}/signed-url/"
        ),
        json={"expires_in": 60, "content_disposition": "attachment"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert signed_url_response.status_code == 200, signed_url_response.text
    download_response = await client.get(signed_url_response.json()["url"])
    assert download_response.status_code == 200, download_response.text
    assert download_response.content == b"representative-pdf"
    assert download_response.headers["content-type"] == "application/pdf"
    assert outbound_public["result"] == {
        "kind": "outbound_http",
        "delivery_status": "delivered",
    }
    assert set(outbound_public["result"]) == {"kind", "delivery_status"}

    wrong_flow_response = await client.get(
        f"/api/v1/flows/{text_flow['id']}/runs/{artifact_run['id']}/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert wrong_flow_response.status_code == 404, wrong_flow_response.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_public_projects_file_backed_text_overflow(
    client,
    db_container,
    admin_token,
    monkeypatch,
):
    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        _noop_dispatch_flow_run_recoverably_after_commit,
    )
    space_id = await _create_space(client, token=admin_token)
    flow = await _create_published_flow(
        client,
        token=admin_token,
        space_id=space_id,
        output_type="text",
    )
    run_response = await client.post(
        f"/api/v1/flows/{flow['id']}/runs/",
        json={
            "expected_flow_version": flow["published_version"],
            "input_payload_json": {"text": "produce result"},
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert run_response.status_code == 201, run_response.text
    run = run_response.json()
    (
        current_file_id,
        historical_file_id,
        declared_file_id,
    ) = await _mark_run_completed_with_file_backed_text(
        db_container=db_container,
        run=run,
        flow=flow,
    )

    response = await client.get(
        f"/api/v1/flows/{flow['id']}/runs/{run['id']}/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200, response.text
    public = response.json()
    assert public["result"]["kind"] == "file_backed_text"
    assert public["result"]["preview"] == "current"
    assert public["result"]["file"]["file_id"] == str(current_file_id)
    assert public["result"]["file"]["source"] == "generated_output"
    assert public["result"]["file"]["attempt_no"] == 2
    assert public["result"]["file"]["availability"] == "available"
    assert public["result"]["kind"] != "inline_text"
    result_file_ids = {item["file_id"] for item in public["result_files"]}
    assert len(public["result_files"]) == 2
    assert result_file_ids == {str(current_file_id), str(declared_file_id)}
    assert str(historical_file_id) not in result_file_ids

    steps_response = await client.get(
        f"/api/v1/flows/{flow['id']}/runs/{run['id']}/steps/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert steps_response.status_code == 200, steps_response.text
    current_step = next(
        step
        for step in steps_response.json()
        if step["step_id"] == flow["steps"][-1]["id"]
    )
    assert current_step["output_payload_json"] == {
        "text": "current",
        "text_overflow": {
            "generated_file_ids": [str(current_file_id)],
            "inline_text_bytes": 7,
            "full_text_bytes": len("current complete terminal text".encode()),
        },
    }
    current_attempt_files = [
        file
        for file in current_step["result_files"]
        if file["attempt_no"] == current_step["current_attempt_no"]
    ]
    generated_output_files = [
        file for file in current_attempt_files if file["source"] == "generated_output"
    ]
    assert len(generated_output_files) == 1
    assert generated_output_files[0]["file_id"] == str(current_file_id)
    assert generated_output_files[0]["attempt_no"] == 2
    current_attempt_file_ids = {file["file_id"] for file in current_attempt_files}
    assert str(historical_file_id) not in current_attempt_file_ids


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_list_uses_historical_contracts_with_bounded_bulk_queries(
    client,
    db_container,
    admin_token,
    monkeypatch,
):
    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        _noop_dispatch_flow_run_recoverably_after_commit,
    )
    space_id = await _create_space(client, token=admin_token)
    structured_contract = {
        "type": "object",
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
    }
    flow = await _create_published_flow(
        client,
        token=admin_token,
        space_id=space_id,
        output_contract=structured_contract,
    )
    version_one = flow["published_version"]
    create_version_one = await client.post(
        f"/api/v1/flows/{flow['id']}/runs/",
        json={
            "expected_flow_version": version_one,
            "input_payload_json": {"text": "version one"},
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_version_one.status_code == 201, create_version_one.text
    version_one_run = create_version_one.json()
    await _mark_run_completed(
        db_container=db_container,
        run_id=version_one_run["id"],
        output_payload_json={"structured": {"answer": "historical"}},
    )

    unpublish_response = await client.post(
        f"/api/v1/flows/{flow['id']}/unpublish/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert unpublish_response.status_code == 200, unpublish_response.text
    step = flow["steps"][0]
    update_response = await client.patch(
        f"/api/v1/flows/{flow['id']}/",
        json={
            "steps": [
                {
                    "id": step["id"],
                    "assistant_id": step["assistant_id"],
                    "step_order": step["step_order"],
                    "user_description": step["user_description"],
                    "input_source": step["input_source"],
                    "input_type": step["input_type"],
                    "output_mode": "pass_through",
                    "output_type": "text",
                }
            ]
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert update_response.status_code == 200, update_response.text
    publish_response = await client.post(
        f"/api/v1/flows/{flow['id']}/publish/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert publish_response.status_code == 200, publish_response.text
    version_two = publish_response.json()["published_version"]
    assert version_two == version_one + 1

    create_version_two = await client.post(
        f"/api/v1/flows/{flow['id']}/runs/",
        json={
            "expected_flow_version": version_two,
            "input_payload_json": {"text": "version two"},
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_version_two.status_code == 201, create_version_two.text
    version_two_run = create_version_two.json()
    await _mark_run_completed(
        db_container=db_container,
        run_id=version_two_run["id"],
        output_payload_json={"text": "current"},
    )

    selected_table_counts = {
        "flow_versions": 0,
        "flow_run_step_result_files": 0,
        "flow_step_attempts": 0,
    }

    def count_bulk_selects(
        _conn,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        normalized = statement.lower().lstrip()
        if not normalized.startswith("select"):
            return
        for table_name in selected_table_counts:
            if table_name in normalized:
                selected_table_counts[table_name] += 1

    async with db_container() as container:
        sync_bind = container.session().sync_session.get_bind()
        sa.event.listen(sync_bind, "before_cursor_execute", count_bulk_selects)
        try:
            list_response = await client.get(
                f"/api/v1/flows/{flow['id']}/runs/?limit=200",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        finally:
            sa.event.remove(sync_bind, "before_cursor_execute", count_bulk_selects)

    assert list_response.status_code == 200, list_response.text
    runs_by_id = {item["id"]: item for item in list_response.json()["items"]}
    assert runs_by_id[version_one_run["id"]]["flow_version"] == version_one
    assert runs_by_id[version_one_run["id"]]["result"] == {
        "kind": "structured",
        "value": {"answer": "historical"},
        "output_contract": structured_contract,
    }
    assert runs_by_id[version_two_run["id"]]["flow_version"] == version_two
    assert runs_by_id[version_two_run["id"]]["result"] == {
        "kind": "inline_text",
        "text": "current",
    }
    assert selected_table_counts == {
        "flow_versions": 1,
        "flow_run_step_result_files": 1,
        "flow_step_attempts": 1,
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_poll_sanitizes_corrupt_persisted_error_json(
    client,
    db_container,
    admin_token,
    monkeypatch,
):
    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        _noop_dispatch_flow_run_recoverably_after_commit,
    )

    space_id = await _create_space(client, token=admin_token)
    flow = await _create_published_flow(client, token=admin_token, space_id=space_id)

    create_response = await client.post(
        f"/api/v1/flows/{flow['id']}/runs/",
        json={
            "expected_flow_version": flow["published_version"],
            "input_payload_json": {"text": "hello"},
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_response.status_code == 201, create_response.text
    run = create_response.json()

    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == UUID(run["id"]))
            .values(
                status="failed",
                error_json="Step review_policy leaked invalid persisted payload.",
            )
        )
        await session.flush()

    poll_response = await client.get(
        f"/api/v1/flows/{flow['id']}/runs/{run['id']}/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert poll_response.status_code == 200, poll_response.text
    error = poll_response.json()["error"]
    assert error == {
        "schema_version": 1,
        "code": "flow_run_error_payload_invalid",
        "message": "Persisted flow run error payload is invalid.",
        "retryable": False,
        "source": None,
        "step_id": None,
        "step_order": None,
        "details": None,
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_create_rejects_removed_top_level_file_ids_before_body_shape_errors(
    client,
    admin_token,
):
    space_id = await _create_space(client, token=admin_token)
    flow = await _create_published_flow(client, token=admin_token, space_id=space_id)

    response = await client.post(
        f"/api/v1/flows/{flow['id']}/runs/",
        json={
            "expected_flow_version": "not-an-int",
            "file_ids": [str(uuid4())],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 400, response.text
    payload = response.json()
    assert payload["code"] == "flow_run_top_level_file_ids_not_supported"
    assert "step_inputs[step_id].file_ids" in payload["message"]
    assert payload["context"] == {
        "invalid_field": "file_ids",
        "expected_field": "step_inputs[step_id].file_ids",
        "contract_endpoint": "/api/v1/flows/{id}/run-contract/",
    }

    unknown_field_response = await client.post(
        f"/api/v1/flows/{flow['id']}/runs/",
        json={
            "expected_flow_version": flow["published_version"],
            "file_ids": [str(uuid4())],
            "unknown_field": "ignored-before-this-slice",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert unknown_field_response.status_code == 400, unknown_field_response.text
    unknown_field_payload = unknown_field_response.json()
    assert unknown_field_payload["code"] == "flow_run_top_level_file_ids_not_supported"
    assert unknown_field_payload["context"] == payload["context"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_create_rejects_runtime_transcription_cache_key(
    client,
    admin_token,
    monkeypatch,
):
    dispatch_requests: list[object] = []

    async def _record_dispatch(
        *, run_id: UUID, tenant_id: UUID, expected_revision: int
    ) -> None:
        dispatch_requests.append((run_id, tenant_id, expected_revision))

    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        _record_dispatch,
    )

    space_id = await _create_space(client, token=admin_token)
    flow = await _create_published_flow(client, token=admin_token, space_id=space_id)

    response = await client.post(
        f"/api/v1/flows/{flow['id']}/runs/",
        json={
            "expected_flow_version": flow["published_version"],
            "input_payload_json": {
                FLOW_INPUT_TRANSCRIPTION_KEY: "spoofed runtime transcript"
            },
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 400, response.text
    payload = response.json()
    assert payload["code"] == "flow_run_reserved_input_payload_key"
    assert payload["context"] == {"keys": [FLOW_INPUT_TRANSCRIPTION_KEY]}
    assert dispatch_requests == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_create_rejects_unknown_fields_before_dispatch(
    client,
    admin_token,
    monkeypatch,
):
    dispatch_requests: list[object] = []

    async def _record_dispatch(
        *, run_id: UUID, tenant_id: UUID, expected_revision: int
    ) -> None:
        dispatch_requests.append((run_id, tenant_id, expected_revision))

    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        _record_dispatch,
    )

    space_id = await _create_space(client, token=admin_token)
    flow = await _create_published_flow(client, token=admin_token, space_id=space_id)
    assert (
        await _flow_run_first_page_count(client, flow_id=flow["id"], token=admin_token)
        == 0
    )

    top_level_response = await client.post(
        f"/api/v1/flows/{flow['id']}/runs/",
        json={
            "expected_flow_version": flow["published_version"],
            "input_payload_json": {"text": "hello"},
            "client_trace_id": "client-owned-metadata-belongs-outside-this-body",
        },
        headers={
            "Authorization": f"Bearer {admin_token}",
            "X-Request-ID": "flow-top-level-validation",
        },
    )

    assert top_level_response.status_code == 422, top_level_response.text
    assert "extra_forbidden" in _validation_error_types(
        top_level_response.json(), request_id="flow-top-level-validation"
    )
    assert (
        "client-owned-metadata-belongs-outside-this-body" not in top_level_response.text
    )
    assert dispatch_requests == []
    assert (
        await _flow_run_first_page_count(client, flow_id=flow["id"], token=admin_token)
        == 0
    )

    nested_response = await client.post(
        f"/api/v1/flows/{flow['id']}/runs/",
        json={
            "expected_flow_version": flow["published_version"],
            "input_payload_json": {"text": "hello"},
            "step_inputs": {
                flow["steps"][0]["id"]: {
                    "file_ids": [],
                    "file_id": str(uuid4()),
                }
            },
        },
        headers={
            "Authorization": f"Bearer {admin_token}",
            "X-Request-ID": "flow-nested-validation",
        },
    )

    assert nested_response.status_code == 422, nested_response.text
    assert "extra_forbidden" in _validation_error_types(
        nested_response.json(), request_id="flow-nested-validation"
    )
    assert dispatch_requests == []
    assert (
        await _flow_run_first_page_count(client, flow_id=flow["id"], token=admin_token)
        == 0
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_create_rejects_missing_required_runtime_step_inputs(
    client,
    admin_token,
    monkeypatch,
):
    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        _noop_dispatch_flow_run_recoverably_after_commit,
    )

    space_id = await _create_space(client, token=admin_token)
    flow = await _create_published_required_runtime_input_flow(
        client,
        token=admin_token,
        space_id=space_id,
    )
    flow_id = flow["id"]

    contract_response = await client.get(
        f"/api/v1/flows/{flow_id}/run-contract/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert contract_response.status_code == 200, contract_response.text
    contract = contract_response.json()
    required_step = contract["steps_requiring_input"][0]
    assert required_step["required"] is True

    base_payload = {
        "expected_flow_version": flow["published_version"],
        "input_payload_json": {"text": "hello"},
    }
    expected_context = {"step_ids": [required_step["step_id"]]}

    omitted_response = await client.post(
        f"/api/v1/flows/{flow_id}/runs/",
        json=base_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert omitted_response.status_code == 400, omitted_response.text
    omitted_payload = omitted_response.json()
    assert omitted_payload["code"] == "flow_run_required_step_input_missing"
    assert omitted_payload["message"] == "Required runtime input files are missing."
    assert omitted_payload["context"] == expected_context

    empty_response = await client.post(
        f"/api/v1/flows/{flow_id}/runs/",
        json={**base_payload, "step_inputs": {}},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert empty_response.status_code == 400, empty_response.text
    empty_payload = empty_response.json()
    assert empty_payload["code"] == "flow_run_required_step_input_missing"
    assert empty_payload["message"] == omitted_payload["message"]
    assert empty_payload["context"] == expected_context


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_runtime_file_delete_removes_orphan_upload(
    client,
    admin_token,
):
    space_id = await _create_space(client, token=admin_token)
    flow = await _create_published_required_runtime_input_flow(
        client,
        token=admin_token,
        space_id=space_id,
    )
    flow_id = flow["id"]

    contract_response = await client.get(
        f"/api/v1/flows/{flow_id}/run-contract/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert contract_response.status_code == 200, contract_response.text
    required_step = contract_response.json()["steps_requiring_input"][0]

    uploaded = await _upload_runtime_document(
        client,
        flow_id=flow_id,
        step_id=required_step["step_id"],
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    runtime_response = await client.get(
        f"/api/v1/flows/{flow_id}/published/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert runtime_response.status_code == 200, runtime_response.text
    delete_path = runtime_response.json()["runtime_paths"][
        "delete_runtime_file_template"
    ].replace("{file_id}", uploaded["id"])

    delete_response = await client.delete(
        delete_path,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert delete_response.status_code == 204, delete_response.text
    assert delete_response.content == b""

    second_delete_response = await client.delete(
        delete_path,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert second_delete_response.status_code == 404, second_delete_response.text
    assert second_delete_response.json()["code"] == "not_found"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_runtime_file_delete_hides_upload_bound_to_another_flow(
    client,
    admin_token,
):
    space_id = await _create_space(client, token=admin_token)
    target_flow = await _create_published_required_runtime_input_flow(
        client,
        token=admin_token,
        space_id=space_id,
    )
    source_flow = await _create_published_required_runtime_input_flow(
        client,
        token=admin_token,
        space_id=space_id,
    )

    source_contract_response = await client.get(
        f"/api/v1/flows/{source_flow['id']}/run-contract/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert source_contract_response.status_code == 200, source_contract_response.text
    source_step = source_contract_response.json()["steps_requiring_input"][0]
    uploaded = await _upload_runtime_document(
        client,
        flow_id=source_flow["id"],
        step_id=source_step["step_id"],
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    delete_response = await client.delete(
        f"/api/v1/flows/{target_flow['id']}/runtime-files/{uploaded['id']}/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert delete_response.status_code == 404, delete_response.text
    assert delete_response.json()["code"] == "not_found"

    source_delete_response = await client.delete(
        f"/api/v1/flows/{source_flow['id']}/runtime-files/{uploaded['id']}/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert source_delete_response.status_code == 204, source_delete_response.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_rejects_runtime_file_uploaded_for_another_flow(
    client,
    admin_token,
):
    space_id = await _create_space(client, token=admin_token)
    target_flow = await _create_published_required_runtime_input_flow(
        client,
        token=admin_token,
        space_id=space_id,
    )
    source_flow = await _create_published_required_runtime_input_flow(
        client,
        token=admin_token,
        space_id=space_id,
    )

    target_contract_response = await client.get(
        f"/api/v1/flows/{target_flow['id']}/run-contract/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert target_contract_response.status_code == 200, target_contract_response.text
    target_step = target_contract_response.json()["steps_requiring_input"][0]

    source_contract_response = await client.get(
        f"/api/v1/flows/{source_flow['id']}/run-contract/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert source_contract_response.status_code == 200, source_contract_response.text
    source_step = source_contract_response.json()["steps_requiring_input"][0]
    uploaded = await _upload_runtime_document(
        client,
        flow_id=source_flow["id"],
        step_id=source_step["step_id"],
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    run_response = await client.post(
        f"/api/v1/flows/{target_flow['id']}/runs/",
        json={
            "expected_flow_version": target_flow["published_version"],
            "input_payload_json": {"text": "hello"},
            "step_inputs": {target_step["step_id"]: {"file_ids": [uploaded["id"]]}},
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert run_response.status_code == 400, run_response.text
    payload = run_response.json()
    assert payload["code"] == "flow_run_file_not_bound_to_flow"
    assert payload["context"] == {
        "step_id": target_step["step_id"],
        "file_ids": [uploaded["id"]],
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_runtime_file_delete_rejects_attached_run_input(
    client,
    admin_token,
    monkeypatch,
):
    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        _noop_dispatch_flow_run_recoverably_after_commit,
    )

    space_id = await _create_space(client, token=admin_token)
    flow = await _create_published_required_runtime_input_flow(
        client,
        token=admin_token,
        space_id=space_id,
    )
    flow_id = flow["id"]

    contract_response = await client.get(
        f"/api/v1/flows/{flow_id}/run-contract/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert contract_response.status_code == 200, contract_response.text
    required_step = contract_response.json()["steps_requiring_input"][0]
    step_id = required_step["step_id"]
    uploaded = await _upload_runtime_document(
        client,
        flow_id=flow_id,
        step_id=step_id,
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    run_response = await client.post(
        f"/api/v1/flows/{flow_id}/runs/",
        json={
            "expected_flow_version": flow["published_version"],
            "input_payload_json": {"text": "hello"},
            "step_inputs": {step_id: {"file_ids": [uploaded["id"]]}},
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert run_response.status_code == 201, run_response.text

    delete_response = await client.delete(
        f"/api/v1/flows/{flow_id}/runtime-files/{uploaded['id']}/",
        headers={
            "Authorization": f"Bearer {admin_token}",
            "X-Correlation-ID": "flow-runtime-file-attached-delete",
        },
    )
    assert delete_response.status_code == 409, delete_response.text
    payload = delete_response.json()
    assert payload["eneo_error_code"] == ErrorCodes.CONFLICT
    assert payload["code"] == "flow_runtime_file_attached"
    assert payload["context"] == {"flow_id": flow_id, "file_id": uploaded["id"]}
    assert payload["request_id"] == "flow-runtime-file-attached-delete"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_runtime_file_delete_rejects_attached_rerun_input(
    client,
    db_container,
    admin_token,
    monkeypatch,
):
    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        _noop_dispatch_flow_run_recoverably_after_commit,
    )
    monkeypatch.setattr(
        flow_run_rerun_router,
        "dispatch_flow_run_recoverably_after_commit",
        _noop_dispatch_flow_run_recoverably_after_commit,
    )

    flow, run, step_id, _initial_upload = await _create_completed_runtime_input_run(
        client=client,
        db_container=db_container,
        admin_token=admin_token,
    )
    flow_id = flow["id"]
    rerun_upload = await _upload_runtime_document(
        client,
        flow_id=flow_id,
        step_id=step_id,
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    rerun_response = await client.post(
        f"/api/v1/flows/{flow_id}/runs/{run['id']}/steps/{step_id}/rerun/",
        json={
            "expected_run_revision": run["revision"],
            "reason": "Replace the source document for the rerun.",
            "step_inputs": {step_id: {"file_ids": [rerun_upload["id"]]}},
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert rerun_response.status_code == 202, rerun_response.text
    assert rerun_response.json()["status"] == "queued"

    delete_response = await client.delete(
        f"/api/v1/flows/{flow_id}/runtime-files/{rerun_upload['id']}/",
        headers={
            "Authorization": f"Bearer {admin_token}",
            "X-Correlation-ID": "flow-runtime-file-rerun-attached-delete",
        },
    )
    assert delete_response.status_code == 409, delete_response.text
    payload = delete_response.json()
    assert payload["eneo_error_code"] == ErrorCodes.CONFLICT
    assert payload["code"] == "flow_runtime_file_attached"
    assert payload["context"] == {"flow_id": flow_id, "file_id": rerun_upload["id"]}
    assert payload["request_id"] == "flow-runtime-file-rerun-attached-delete"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_runtime_file_delete_removes_unselected_post_run_upload(
    client,
    db_container,
    admin_token,
    monkeypatch,
):
    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        _noop_dispatch_flow_run_recoverably_after_commit,
    )

    flow, run, step_id, _initial_upload = await _create_completed_runtime_input_run(
        client=client,
        db_container=db_container,
        admin_token=admin_token,
    )
    flow_id = flow["id"]
    selected_rerun_upload = await _upload_runtime_document(
        client,
        flow_id=flow_id,
        step_id=step_id,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    unselected_upload = await _upload_runtime_document(
        client,
        flow_id=flow_id,
        step_id=step_id,
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    rerun_response = await client.post(
        f"/api/v1/flows/{flow_id}/runs/{run['id']}/steps/{step_id}/rerun/",
        json={
            "expected_run_revision": run["revision"],
            "reason": "Rerun with a selected replacement document.",
            "step_inputs": {step_id: {"file_ids": [selected_rerun_upload["id"]]}},
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert rerun_response.status_code == 202, rerun_response.text

    delete_response = await client.delete(
        f"/api/v1/flows/{flow_id}/runtime-files/{unselected_upload['id']}/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert delete_response.status_code == 204, delete_response.text
    assert delete_response.content == b""


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_runtime_file_delete_allows_service_key_owned_orphan_upload(
    client,
    admin_token,
):
    space_id = await _create_space(client, token=admin_token)
    flow = await _create_published_required_runtime_input_flow(
        client,
        token=admin_token,
        space_id=space_id,
    )
    flow_id = flow["id"]
    service_key = await _create_flow_service_key(client, token=admin_token)
    service_headers = {"X-API-Key": service_key}

    contract_response = await client.get(
        f"/api/v1/flows/{flow_id}/run-contract/",
        headers=service_headers,
    )
    assert contract_response.status_code == 200, contract_response.text
    required_step = contract_response.json()["steps_requiring_input"][0]
    uploaded = await _upload_runtime_document(
        client,
        flow_id=flow_id,
        step_id=required_step["step_id"],
        headers=service_headers,
    )

    delete_response = await client.delete(
        f"/api/v1/flows/{flow_id}/runtime-files/{uploaded['id']}/",
        headers=service_headers,
    )
    assert delete_response.status_code == 204, delete_response.text
    assert delete_response.content == b""


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_runtime_file_delete_hides_other_principal_attached_file(
    client,
    admin_token,
    monkeypatch,
):
    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        _noop_dispatch_flow_run_recoverably_after_commit,
    )

    space_id = await _create_space(client, token=admin_token)
    flow = await _create_published_required_runtime_input_flow(
        client,
        token=admin_token,
        space_id=space_id,
    )
    flow_id = flow["id"]
    owner_service_key = await _create_flow_service_key(client, token=admin_token)
    other_service_key = await _create_flow_service_key(client, token=admin_token)
    owner_headers = {"X-API-Key": owner_service_key}
    other_headers = {
        "X-API-Key": other_service_key,
        "X-Correlation-ID": "flow-runtime-file-cross-owner-delete",
    }

    contract_response = await client.get(
        f"/api/v1/flows/{flow_id}/run-contract/",
        headers=owner_headers,
    )
    assert contract_response.status_code == 200, contract_response.text
    required_step = contract_response.json()["steps_requiring_input"][0]
    step_id = required_step["step_id"]
    uploaded = await _upload_runtime_document(
        client,
        flow_id=flow_id,
        step_id=step_id,
        headers=owner_headers,
    )

    run_response = await client.post(
        f"/api/v1/flows/{flow_id}/runs/",
        json={
            "expected_flow_version": flow["published_version"],
            "input_payload_json": {"text": "hello"},
            "step_inputs": {step_id: {"file_ids": [uploaded["id"]]}},
        },
        headers=owner_headers,
    )
    assert run_response.status_code == 201, run_response.text

    delete_response = await client.delete(
        f"/api/v1/flows/{flow_id}/runtime-files/{uploaded['id']}/",
        headers=other_headers,
    )
    assert delete_response.status_code == 404, delete_response.text
    payload = delete_response.json()
    assert payload["eneo_error_code"] == ErrorCodes.NOT_FOUND
    assert payload["code"] == "not_found"
    assert payload["request_id"] == "flow-runtime-file-cross-owner-delete"

    owner_delete_response = await client.delete(
        f"/api/v1/flows/{flow_id}/runtime-files/{uploaded['id']}/",
        headers=owner_headers,
    )
    assert owner_delete_response.status_code == 409, owner_delete_response.text
    assert owner_delete_response.json()["code"] == "flow_runtime_file_attached"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_review_edit_returns_typed_contract_error_for_invalid_payload(
    client,
    db_container,
    admin_token,
    monkeypatch,
):
    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        _noop_dispatch_flow_run_recoverably_after_commit,
    )

    space_id = await _create_space(client, token=admin_token)
    flow = await _create_published_flow(client, token=admin_token, space_id=space_id)
    run_response = await client.post(
        f"/api/v1/flows/{flow['id']}/runs/",
        json={
            "expected_flow_version": flow["published_version"],
            "input_payload_json": {"text": "hello"},
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert run_response.status_code == 201, run_response.text
    run = run_response.json()
    output_contract = {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string"}},
        "additionalProperties": False,
    }
    checkpoint_id = await _open_first_step_review_checkpoint(
        db_container=db_container,
        run=run,
        flow=flow,
        output_contract=output_contract,
        current_payload_json={
            "text": '{"summary":"Original."}',
            "structured": {"summary": "Original."},
        },
    )

    response = await client.patch(
        f"/api/v1/flows/{flow['id']}/runs/{run['id']}/review-checkpoints/{checkpoint_id}/",
        json={
            "expected_checkpoint_revision": 1,
            "current_payload_json": {
                "text": '{"wrong":"shape"}',
                "structured": {"wrong": "shape"},
            },
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 400, response.text
    payload = response.json()
    assert payload["code"] == "typed_io_contract_violation"
    assert "Review checkpoint step 1 output" in payload["message"]
    assert payload["context"] == {
        "checkpoint_id": checkpoint_id,
        "step_id": flow["steps"][0]["id"],
        "step_order": 1,
        "payload_field": "structured",
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_consumer_golden_journey_uses_review_runtime_paths(
    client,
    db_container,
    admin_token,
    monkeypatch,
):
    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        _noop_dispatch_flow_run_recoverably_after_commit,
    )
    monkeypatch.setattr(
        flow_run_review_router,
        "dispatch_flow_run_recoverably_after_commit",
        _noop_dispatch_flow_run_recoverably_after_commit,
    )

    output_contract = {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string"}},
        "additionalProperties": False,
    }
    space_id = await _create_space(client, token=admin_token)
    flow = await _create_published_flow(
        client,
        token=admin_token,
        space_id=space_id,
        review_output_contract=output_contract,
    )

    published_response = await client.get(
        f"/api/v1/flows/{flow['id']}/published/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert published_response.status_code == 200, published_response.text
    runtime_paths = published_response.json()["runtime_paths"]
    review_paths = runtime_paths["review_checkpoints"]

    contract_response = await client.get(
        runtime_paths["run_contract"],
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert contract_response.status_code == 200, contract_response.text
    contract = contract_response.json()
    assert contract["final_output"]["output_type"] == "json"
    assert contract["steps_requiring_review"][0]["step_id"] == flow["steps"][0]["id"]
    assert contract["steps_requiring_review"][0]["output_contract"] == output_contract

    run_response = await client.post(
        runtime_paths["create_run"],
        json={
            "expected_flow_version": flow["published_version"],
            "input_payload_json": {"text": "hello"},
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert run_response.status_code == 201, run_response.text
    run = run_response.json()

    active_before_checkpoint_response = await client.get(
        _runtime_path(review_paths["active_template"], run_id=run["id"]),
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert active_before_checkpoint_response.status_code == 200
    assert active_before_checkpoint_response.json() is None

    checkpoint_id = await _open_first_step_review_checkpoint(
        db_container=db_container,
        run=run,
        flow=flow,
        output_contract=output_contract,
        current_payload_json={
            "text": '{"summary":"Original."}',
            "structured": {"summary": "Original."},
        },
    )
    active_path = _runtime_path(review_paths["active_template"], run_id=run["id"])
    active_response = await client.get(
        active_path,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert active_response.status_code == 200, active_response.text
    active_checkpoint = active_response.json()
    assert active_checkpoint["id"] == checkpoint_id
    assert active_checkpoint["output_contract"] == output_contract

    edit_path = _runtime_path(
        review_paths["edit_template"],
        run_id=run["id"],
        checkpoint_id=checkpoint_id,
    )
    invalid_edit_response = await client.patch(
        edit_path,
        json={
            "expected_checkpoint_revision": active_checkpoint["revision"],
            "current_payload_json": {
                "text": '{"wrong":"shape"}',
                "structured": {"wrong": "shape"},
            },
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert invalid_edit_response.status_code == 400, invalid_edit_response.text
    assert invalid_edit_response.json()["code"] == "typed_io_contract_violation"

    valid_edit_response = await client.patch(
        edit_path,
        json={
            "expected_checkpoint_revision": active_checkpoint["revision"],
            "current_payload_json": {
                "text": '{"summary":"Approved."}',
                "structured": {"summary": "Approved."},
            },
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert valid_edit_response.status_code == 200, valid_edit_response.text
    edited_checkpoint = valid_edit_response.json()

    approve_response = await client.post(
        _runtime_path(
            review_paths["approve_template"],
            run_id=run["id"],
            checkpoint_id=checkpoint_id,
        ),
        json={"expected_checkpoint_revision": edited_checkpoint["revision"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert approve_response.status_code == 200, approve_response.text
    approved_checkpoint = approve_response.json()

    missing_resume_idempotency_response = await client.post(
        _runtime_path(
            review_paths["resume_template"],
            run_id=run["id"],
            checkpoint_id=checkpoint_id,
        ),
        json={"expected_checkpoint_revision": approved_checkpoint["revision"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert missing_resume_idempotency_response.status_code == 400, (
        missing_resume_idempotency_response.text
    )
    missing_resume_idempotency_payload = missing_resume_idempotency_response.json()
    assert (
        missing_resume_idempotency_payload["code"]
        == "flow_review_idempotency_key_required"
    )
    assert (
        missing_resume_idempotency_payload["message"]
        == "Review resume requires an Idempotency-Key header."
    )
    assert "eneo_error_code" in missing_resume_idempotency_payload

    resume_response = await client.post(
        _runtime_path(
            review_paths["resume_template"],
            run_id=run["id"],
            checkpoint_id=checkpoint_id,
        ),
        json={"expected_checkpoint_revision": approved_checkpoint["revision"]},
        headers={
            "Authorization": f"Bearer {admin_token}",
            "Idempotency-Key": f"resume:{uuid4().hex}",
        },
    )
    assert resume_response.status_code == 202, resume_response.text
    resumed_payload = resume_response.json()
    assert resumed_payload["checkpoint"]["id"] == checkpoint_id
    assert resumed_payload["run"]["id"] == run["id"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_service_key_can_drive_human_review_runtime_paths(
    client,
    db_container,
    admin_token,
    monkeypatch,
):
    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        _noop_dispatch_flow_run_recoverably_after_commit,
    )
    monkeypatch.setattr(
        flow_run_review_router,
        "dispatch_flow_run_recoverably_after_commit",
        _noop_dispatch_flow_run_recoverably_after_commit,
    )

    output_contract = {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string"}},
        "additionalProperties": False,
    }
    space_id = await _create_space(client, token=admin_token)
    flow = await _create_published_flow(
        client,
        token=admin_token,
        space_id=space_id,
        review_output_contract=output_contract,
    )
    service_key = await _create_flow_service_key(client, token=admin_token)
    other_service_key = await _create_flow_service_key(client, token=admin_token)
    service_headers = {"X-API-Key": service_key}
    other_service_headers = {"X-API-Key": other_service_key}

    published_response = await client.get(
        f"/api/v1/flows/{flow['id']}/published/",
        headers=service_headers,
    )
    assert published_response.status_code == 200, published_response.text
    runtime_paths = published_response.json()["runtime_paths"]
    review_paths = runtime_paths["review_checkpoints"]

    contract_response = await client.get(
        runtime_paths["run_contract"],
        headers=service_headers,
    )
    assert contract_response.status_code == 200, contract_response.text
    contract = contract_response.json()
    assert contract["steps_requiring_review"][0]["step_id"] == flow["steps"][0]["id"]

    run_response = await client.post(
        runtime_paths["create_run"],
        json={
            "expected_flow_version": flow["published_version"],
            "input_payload_json": {"text": "hello from integration"},
        },
        headers={
            **service_headers,
            "Idempotency-Key": f"service-flow-run:{uuid4().hex}",
        },
    )
    assert run_response.status_code == 201, run_response.text
    run = run_response.json()
    assert run["principal_type"] == "service_key"
    assert "user_id" not in run

    immediate_poll_response = await client.get(
        _runtime_path(runtime_paths["get_run_template"], run_id=run["id"]),
        headers=service_headers,
    )
    assert immediate_poll_response.status_code == 200, immediate_poll_response.text
    assert immediate_poll_response.json()["id"] == run["id"]

    active_path = _runtime_path(review_paths["active_template"], run_id=run["id"])
    active_before_checkpoint_response = await client.get(
        active_path,
        headers=service_headers,
    )
    assert active_before_checkpoint_response.status_code == 200
    assert active_before_checkpoint_response.json() is None

    checkpoint_id = await _open_first_step_review_checkpoint(
        db_container=db_container,
        run=run,
        flow=flow,
        output_contract=output_contract,
        current_payload_json={
            "text": '{"summary":"Original service-key result."}',
            "structured": {"summary": "Original service-key result."},
        },
    )
    active_response = await client.get(active_path, headers=service_headers)
    assert active_response.status_code == 200, active_response.text
    active_checkpoint = active_response.json()
    assert active_checkpoint["id"] == checkpoint_id
    assert active_checkpoint["requester_principal_type"] == "service_key"

    other_key_active_response = await client.get(
        active_path,
        headers=other_service_headers,
    )
    assert other_key_active_response.status_code == 403, other_key_active_response.text
    assert other_key_active_response.json()["code"] == "flow_run_access_denied"

    edit_path = _runtime_path(
        review_paths["edit_template"],
        run_id=run["id"],
        checkpoint_id=checkpoint_id,
    )
    edit_response = await client.patch(
        edit_path,
        json={
            "expected_checkpoint_revision": active_checkpoint["revision"],
            "current_payload_json": {
                "text": '{"summary":"Reviewed by service integration."}',
                "structured": {"summary": "Reviewed by service integration."},
            },
        },
        headers=service_headers,
    )
    assert edit_response.status_code == 200, edit_response.text
    edited_checkpoint = edit_response.json()
    assert edited_checkpoint["decided_by_principal_type"] == "service_key"

    approve_response = await client.post(
        _runtime_path(
            review_paths["approve_template"],
            run_id=run["id"],
            checkpoint_id=checkpoint_id,
        ),
        json={"expected_checkpoint_revision": edited_checkpoint["revision"]},
        headers=service_headers,
    )
    assert approve_response.status_code == 200, approve_response.text
    approved_checkpoint = approve_response.json()
    assert approved_checkpoint["decided_by_principal_type"] == "service_key"

    resume_response = await client.post(
        _runtime_path(
            review_paths["resume_template"],
            run_id=run["id"],
            checkpoint_id=checkpoint_id,
        ),
        json={"expected_checkpoint_revision": approved_checkpoint["revision"]},
        headers={
            **service_headers,
            "Idempotency-Key": f"service-review-resume:{uuid4().hex}",
        },
    )
    assert resume_response.status_code == 202, resume_response.text
    resumed_payload = resume_response.json()
    assert resumed_payload["checkpoint"]["id"] == checkpoint_id
    assert resumed_payload["checkpoint"]["decided_by_principal_type"] == "service_key"
    assert resumed_payload["run"]["id"] == run["id"]

    await _mark_run_completed(db_container=db_container, run_id=run["id"])
    other_key_rerun_response = await client.post(
        f"/api/v1/flows/{flow['id']}/runs/{run['id']}/steps/{flow['steps'][0]['id']}/rerun/",
        json={
            "expected_run_revision": resumed_payload["run"]["revision"],
            "reason": "Other service key cannot rerun this run",
        },
        headers=other_service_headers,
    )
    assert other_key_rerun_response.status_code == 403, other_key_rerun_response.text
    assert other_key_rerun_response.json()["code"] == "flow_run_access_denied"

    rerun_response = await client.post(
        f"/api/v1/flows/{flow['id']}/runs/{run['id']}/steps/{flow['steps'][0]['id']}/rerun/",
        json={
            "expected_run_revision": resumed_payload["run"]["revision"],
            "reason": "Service-key rerun of own run",
        },
        headers=service_headers,
    )
    assert rerun_response.status_code == 202, rerun_response.text
    rerun_payload = rerun_response.json()
    assert rerun_payload["run"]["id"] == run["id"]
    assert rerun_payload["rerun_step_id"] == flow["steps"][0]["id"]
    assert rerun_payload["status"] == "queued"
