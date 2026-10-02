"""A deleted (retired) flow keeps its run history readable with the reader's
current authorization, and refuses every action that would change a run."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.flow_tables import (
    FlowRunReviewCheckpoints,
    FlowRuns,
    FlowRunStepInputFiles,
    Flows,
    FlowSteps,
)
from eneo.database.tables.security_classifications_table import (
    SecurityClassification,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.flows import FlowRepository
from eneo.flows.api import flow_run_lifecycle_router
from eneo.flows.api.flow_models import (
    FLOW_RUN_REVIEW_CHECKPOINT_REJECT_REQUEST_EXAMPLE,
    FLOW_TRANSCRIPT_CORRECTIONS_EDIT_REQUEST_EXAMPLE,
)
from eneo.flows.api.flow_transcript_regeneration_router import (
    FLOW_TRANSCRIPT_REGENERATION_REQUEST_EXAMPLE,
)
from tests.integration.flows import test_flow_consumer_api_contract as consumer
from tests.integration.flows.test_flow_evidence_api_contracts import (
    _add_space_membership,
    _create_view_only_user_and_token,
    _replace_flow_definition_with_outbound_http_snapshot,
    _seed_trace_view_flow_run_contract_data,
    _seed_transcript_words_for_audit_read,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

admin_token = consumer.admin_token


async def _seed_owned_run(
    *,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> tuple[dict[str, str], str]:
    """A published flow with one completed run whose owner is a space viewer
    holding the trace permission."""
    seeded, _owner, owner_token = await _seed_trace_view_flow_run_contract_data(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
        include_review_checkpoint_lineage=True,
    )
    # The run detail and graph read the published definition, so it must be
    # one the runtime can parse.
    await _replace_flow_definition_with_outbound_http_snapshot(
        db_container=db_container, seeded=seeded
    )
    return seeded, owner_token


async def _retire_flow(*, db_container, flow_id: str, tenant_id: UUID) -> None:
    async with db_container() as container:
        await FlowRepository(session=container.session()).delete(
            UUID(flow_id), tenant_id
        )


def _run_path(seeded: dict[str, str]) -> str:
    return f"/api/v1/flows/{seeded['flow_id']}/runs/{seeded['run_id']}"


def _history_read_paths(seeded: dict[str, str]) -> list[str]:
    run_path = _run_path(seeded)
    return [
        f"{run_path}/",
        f"{run_path}/status/",
        f"{run_path}/steps/",
        f"/api/v1/flows/{seeded['flow_id']}/graph/?run_id={seeded['run_id']}",
        f"{run_path}/evidence/",
        f"{run_path}/provider-calls/",
        f"{run_path}/evidence/export",
        f"{run_path}/review-checkpoints/active/",
        f"{run_path}/review-checkpoints/{seeded['review_checkpoint_id']}/edits",
        f"{run_path}/transcript-corrections/",
        f"{run_path}/steps/{seeded['step_id']}/transcript-words/",
        f"{run_path}/steps/{seeded['step_id']}/attempts/1/transcript-source/",
    ]


async def test_deleted_flow_run_list_status_detail_steps_readable(
    client,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> None:
    seeded, owner_token = await _seed_owned_run(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
    )
    await _seed_transcript_words_for_audit_read(
        db_container=db_container, seeded=seeded, tenant_id=admin_user.tenant_id
    )
    async with db_container() as container:
        input_file_id = await container.session().scalar(
            sa.select(FlowRunStepInputFiles.file_id).where(
                FlowRunStepInputFiles.flow_run_id == UUID(seeded["run_id"])
            )
        )
    await _retire_flow(
        db_container=db_container,
        flow_id=seeded["flow_id"],
        tenant_id=admin_user.tenant_id,
    )
    headers = {"Authorization": f"Bearer {owner_token}"}

    listing = await client.get(
        f"/api/v1/flows/{seeded['flow_id']}/runs/", headers=headers
    )
    assert listing.status_code == 200, listing.text
    assert [item["id"] for item in listing.json()["items"]] == [seeded["run_id"]]

    for path in _history_read_paths(seeded):
        response = await client.get(path, headers=headers)
        assert response.status_code == 200, (path, response.text)

    signed = await client.post(
        f"{_run_path(seeded)}/input-files/{input_file_id}/signed-url/",
        json={"expires_in": 60, "content_disposition": "attachment"},
        headers=headers,
    )
    assert signed.status_code == 200, signed.text


async def test_deleted_flow_evidence_export_and_provider_calls_readable_with_current_authorization(
    client,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> None:
    seeded, owner_token = await _seed_owned_run(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
    )
    await _retire_flow(
        db_container=db_container,
        flow_id=seeded["flow_id"],
        tenant_id=admin_user.tenant_id,
    )
    headers = {"Authorization": f"Bearer {owner_token}"}
    run_path = _run_path(seeded)
    raw_export = f"{run_path}/evidence/export?detail=raw&reason=case_review"

    assert (await client.get(raw_export, headers=headers)).status_code == 200

    # A flow marked sensitive after deletion: the export gate still applies,
    # the redacted view stays readable.
    async with db_container() as container:
        await container.session().execute(
            sa.update(Flows)
            .where(Flows.id == UUID(seeded["flow_id"]))
            .values(metadata_json={"care_data_policy": {"sensitive": True}})
        )
    export = await client.get(f"{run_path}/evidence/export", headers=headers)
    assert export.status_code == 403, export.text
    assert export.json()["code"] == "flow_run_evidence_forbidden"
    assert export.json()["context"]["auth_layer"] == "flow_runtime_policy"
    assert (
        await client.get(f"{run_path}/evidence/", headers=headers)
    ).status_code == 200

    # A space reclassified after deletion: the current classification decides.
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.update(Flows)
            .where(Flows.id == UUID(seeded["flow_id"]))
            .values(metadata_json=None)
        )
        classification = SecurityClassification(
            name=f"Level three {uuid4().hex[:8]}",
            description=None,
            security_level=3,
            tenant_id=admin_user.tenant_id,
        )
        session.add(classification)
        await session.flush()
        await session.execute(
            sa.update(Spaces)
            .where(Spaces.id == UUID(seeded["space_id"]))
            .values(security_classification_id=classification.id)
        )
    raw = await client.get(raw_export, headers=headers)
    assert raw.status_code == 403, raw.text
    assert raw.json()["code"] == "flow_run_evidence_raw_export_forbidden"
    redacted = await client.get(f"{run_path}/evidence/export", headers=headers)
    assert redacted.status_code == 200, redacted.text
    provider_calls = await client.get(f"{run_path}/provider-calls/", headers=headers)
    assert provider_calls.status_code == 200, provider_calls.text


async def test_deleted_flow_history_still_denies_non_member_and_foreign_run_owner(
    client,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> None:
    seeded, owner_token = await _seed_owned_run(
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
    run_path = _run_path(seeded)
    viewer_headers = {"Authorization": f"Bearer {viewer_token}"}
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    async def outcomes(headers: dict[str, str]) -> list[tuple[str, int, str]]:
        responses = [
            (path, await client.get(path, headers=headers))
            for path in _history_read_paths(seeded)
        ]
        return [
            (path, response.status_code, response.json().get("code"))
            for path, response in responses
        ]

    async with db_container() as container:
        owner_id = await container.session().scalar(
            sa.select(FlowRuns.principal_user_id).where(
                FlowRuns.id == UUID(seeded["run_id"])
            )
        )
    assert owner_id is not None

    async def remove_owner_from_space() -> None:
        async with db_container() as container:
            await container.session().execute(
                sa.text(
                    "DELETE FROM spaces_users WHERE space_id = :space_id "
                    "AND user_id = :user_id"
                ),
                {"space_id": seeded["space_id"], "user_id": str(owner_id)},
            )

    # Refusals on the live flow are the reference the retired flow must match.
    live_foreign = await outcomes(viewer_headers)
    await remove_owner_from_space()
    live_removed_owner = await outcomes(owner_headers)
    await _add_space_membership(
        db_container=db_container,
        space_id=UUID(seeded["space_id"]),
        user_id=owner_id,
    )
    await _retire_flow(
        db_container=db_container,
        flow_id=seeded["flow_id"],
        tenant_id=admin_user.tenant_id,
    )

    # A member who did not start the run: the same refusal as on a live flow.
    foreign = await client.get(f"{run_path}/steps/", headers=viewer_headers)
    assert foreign.status_code == 403, foreign.text
    assert foreign.json()["code"] == "flow_run_access_denied"
    assert await outcomes(viewer_headers) == live_foreign

    # The run owner removed from the space after the deletion: exactly the
    # refusal the live flow gave.
    assert (
        await client.get(f"{run_path}/status/", headers=owner_headers)
    ).status_code == 200
    await remove_owner_from_space()
    assert await outcomes(owner_headers) == live_removed_owner
    assert all(status == 403 for _path, status, _code in live_removed_owner), (
        live_removed_owner
    )

    unknown = await client.get(
        f"/api/v1/flows/{uuid4()}/runs/{seeded['run_id']}/status/",
        headers=owner_headers,
    )
    assert unknown.status_code == 404, unknown.text


async def test_deleted_flow_history_reads_do_not_load_live_steps(
    client,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeded, owner_token = await _seed_owned_run(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
    )
    await _seed_transcript_words_for_audit_read(
        db_container=db_container, seeded=seeded, tenant_id=admin_user.tenant_id
    )
    await _retire_flow(
        db_container=db_container,
        flow_id=seeded["flow_id"],
        tenant_id=admin_user.tenant_id,
    )
    async with db_container() as container:
        await container.session().execute(
            sa.delete(FlowSteps).where(FlowSteps.flow_id == UUID(seeded["flow_id"]))
        )

    async def _live_aggregate_read(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("A history read loaded the live flow aggregate.")

    monkeypatch.setattr(FlowRepository, "get", _live_aggregate_read)
    monkeypatch.setattr(FlowRepository, "_get_flow_steps", _live_aggregate_read)
    headers = {"Authorization": f"Bearer {owner_token}"}

    listing = await client.get(
        f"/api/v1/flows/{seeded['flow_id']}/runs/", headers=headers
    )
    assert listing.status_code == 200, listing.text
    for path in _history_read_paths(seeded):
        response = await client.get(path, headers=headers)
        assert response.status_code == 200, (path, response.text)


async def test_deleted_flow_mutations_still_404(
    client,
    db_container,
    admin_token,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        consumer._noop_dispatch_flow_run_recoverably_after_commit,
    )
    headers = {"Authorization": f"Bearer {admin_token}"}
    space_id = await consumer._create_space(client, token=admin_token)
    flow = await consumer._create_published_flow(
        client, token=admin_token, space_id=space_id
    )
    run_response = await client.post(
        f"/api/v1/flows/{flow['id']}/runs/",
        json={
            "expected_flow_version": flow["published_version"],
            "input_payload_json": {"text": "hello"},
        },
        headers=headers,
    )
    assert run_response.status_code == 201, run_response.text
    run = run_response.json()
    output_contract = {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string"}},
        "additionalProperties": False,
    }
    checkpoint_id = await consumer._open_first_step_review_checkpoint(
        db_container=db_container,
        run=run,
        flow=flow,
        output_contract=output_contract,
        current_payload_json={
            "text": '{"summary":"Original."}',
            "structured": {"summary": "Original."},
        },
        review_mode="edit",
    )

    deleted = await client.delete(f"/api/v1/flows/{flow['id']}/", headers=headers)
    assert deleted.status_code == 204, deleted.text

    flow_path = f"/api/v1/flows/{flow['id']}"
    run_path = f"{flow_path}/runs/{run['id']}"
    review_path = f"{run_path}/review-checkpoints/{checkpoint_id}"
    step_id = flow["steps"][0]["id"]

    # Reads of the open checkpoint still work after the deletion.
    active = await client.get(f"{run_path}/review-checkpoints/active/", headers=headers)
    assert active.status_code == 200, active.text
    assert active.json()["id"] == checkpoint_id

    mutations: list[tuple[str, str, dict[str, object] | None, dict[str, str]]] = [
        (
            "POST",
            f"{flow_path}/runs/",
            {
                "expected_flow_version": flow["published_version"],
                "input_payload_json": {"text": "again"},
            },
            {},
        ),
        ("POST", f"{run_path}/cancel/", None, {}),
        ("POST", f"{run_path}/redispatch/", {}, {}),
        ("POST", f"{run_path}/retry/", None, {"Idempotency-Key": "retired-retry"}),
        (
            "PATCH",
            f"{review_path}/",
            {
                "expected_checkpoint_revision": 1,
                "edited_value": {"summary": "Edited."},
            },
            {},
        ),
        ("POST", f"{review_path}/approve/", {"expected_checkpoint_revision": 1}, {}),
        (
            "POST",
            f"{review_path}/reject/",
            {**FLOW_RUN_REVIEW_CHECKPOINT_REJECT_REQUEST_EXAMPLE},
            {},
        ),
        ("POST", f"{review_path}/resume/", {"expected_checkpoint_revision": 1}, {}),
        (
            "POST",
            f"{review_path}/approve-and-continue/",
            {"expected_checkpoint_revision": 1},
            {},
        ),
        (
            "PATCH",
            f"{run_path}/steps/{step_id}/transcript-corrections/",
            {**FLOW_TRANSCRIPT_CORRECTIONS_EDIT_REQUEST_EXAMPLE},
            {},
        ),
        (
            "POST",
            f"{run_path}/steps/{step_id}/transcript-regenerations/",
            {**FLOW_TRANSCRIPT_REGENERATION_REQUEST_EXAMPLE},
            {"Idempotency-Key": "retired-regeneration"},
        ),
        ("GET", f"{flow_path}/run-contract/", None, {}),
        ("GET", f"{flow_path}/graph/", None, {}),
        ("DELETE", f"{flow_path}/runtime-files/{uuid4()}/", None, {}),
    ]
    for method, path, body, extra_headers in mutations:
        response = await client.request(
            method, path, json=body, headers={**headers, **extra_headers}
        )
        assert response.status_code == 404, (method, path, response.text)

    upload = await client.post(
        f"{flow_path}/steps/{step_id}/runtime-files/",
        files={"upload_file": ("note.txt", b"hello", "text/plain")},
        headers=headers,
    )
    assert upload.status_code == 404, upload.text

    async with db_container() as container:
        session = container.session()
        checkpoint = await session.get(FlowRunReviewCheckpoints, UUID(checkpoint_id))
        assert checkpoint is not None
        assert checkpoint.state == "awaiting_review"
        assert checkpoint.revision == 1
        run_row = await session.get(FlowRuns, UUID(run["id"]))
        assert run_row is not None
        assert run_row.status == "awaiting_review"
        assert (
            await session.scalar(
                sa.select(sa.func.count(FlowRuns.id)).where(
                    FlowRuns.flow_id == UUID(flow["id"])
                )
            )
            == 1
        )


async def test_deleted_flow_history_follows_service_key_ownership_and_scope(
    client,
    db_container,
    admin_token,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        consumer._noop_dispatch_flow_run_recoverably_after_commit,
    )
    space_id = await consumer._create_space(client, token=admin_token)
    other_space_id = await consumer._create_space(client, token=admin_token)
    flow = await consumer._create_published_flow(
        client, token=admin_token, space_id=space_id
    )
    owner_key = await consumer._create_flow_service_key(client, token=admin_token)
    other_key = await consumer._create_flow_service_key(client, token=admin_token)
    elsewhere_key = await consumer._create_flow_service_key(
        client, token=admin_token, scope_type="space", scope_id=other_space_id
    )
    run_response = await client.post(
        f"/api/v1/flows/{flow['id']}/runs/",
        json={
            "expected_flow_version": flow["published_version"],
            "input_payload_json": {"text": "hello"},
        },
        headers={"X-API-Key": owner_key},
    )
    assert run_response.status_code == 201, run_response.text
    run = run_response.json()

    deleted = await client.delete(
        f"/api/v1/flows/{flow['id']}/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert deleted.status_code == 204, deleted.text
    status_path = f"/api/v1/flows/{flow['id']}/runs/{run['id']}/status/"

    owned = await client.get(status_path, headers={"X-API-Key": owner_key})
    assert owned.status_code == 200, owned.text
    listing = await client.get(
        f"/api/v1/flows/{flow['id']}/runs/", headers={"X-API-Key": owner_key}
    )
    assert listing.status_code == 200, listing.text
    assert [item["id"] for item in listing.json()["items"]] == [run["id"]]

    not_owner = await client.get(status_path, headers={"X-API-Key": other_key})
    assert not_owner.status_code == 403, not_owner.text
    assert not_owner.json()["code"] == "flow_run_access_denied"

    scoped_elsewhere = await client.get(
        status_path, headers={"X-API-Key": elsewhere_key}
    )
    assert scoped_elsewhere.status_code == 403, scoped_elsewhere.text
    assert scoped_elsewhere.json()["code"] == "insufficient_scope"
