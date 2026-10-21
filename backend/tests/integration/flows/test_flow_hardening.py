"""Security and lifecycle regressions for the shared-service flow runtime."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from dependency_injector import providers

from eneo.audit.application.audit_service import AuditService
from eneo.database.database import sessionmanager
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.flow_tables import FlowRunReviewCheckpoints
from eneo.flows.definition import ReviewStep
from eneo.flows.flow_models import FlowRunStatus
from eneo.flows.flow_run_worker import maintain_flow_run_lifecycle
from eneo.main.exceptions import BadRequestException, NotFoundException
from tests.integration.flows.test_flow_authorization import _service_key


async def _paused(container, flow):
    definition = flow.definition.model_copy(deep=True)
    definition.steps.append(
        ReviewStep(key="check", name="Check", expires_after_seconds=60)
    )
    service = container.flow_service()
    await service.update_flow(flow.id, definition=definition)
    await service.publish_flow(flow.id)
    runs = container.flow_run_service()
    run = await runs.create_run(flow.id, values={"topic": "private"}, files={})
    await runs.execute_run(run.id)
    return await runs.get_run(run.id)


@pytest.mark.parametrize("role", ["viewer", "editor"])
async def test_members_cannot_read_or_decide_other_principals_runs(
    client,
    db_container,
    published,
    second_editor,
    bearer,
    flows_enabled,
    provider,
    role,
):
    from eneo.database.tables.spaces_table import SpacesUsers

    async with db_container() as container:
        await container.session().execute(
            sa.update(SpacesUsers)
            .where(
                SpacesUsers.space_id == published["space_id"],
                SpacesUsers.user_id == second_editor["user"].id,
            )
            .values(role=role)
        )
        run = await _paused(container, published["flow"])
    base = f"/api/v1/flows/{run.flow_id}/"
    other = second_editor["bearer"]
    for suffix in (
        f"runs/{run.id}/",
        f"runs/{run.id}/status/",
        f"runs/{run.id}/steps/",
    ):
        assert (await client.get(base + suffix, headers=other)).status_code == 404
    listed = await client.get(base + "runs/", headers=other)
    assert listed.json()["items"] == []
    flows = await client.get(
        f"/api/v1/flows/?space_id={published['space_id']}", headers=other
    )
    assert all(row.get("last_run") is None for row in flows.json()["items"])
    checkpoint = run.review_checkpoint
    assert checkpoint is not None
    for decision in ("approve", "reject", "resume"):
        response = await client.post(
            base + f"runs/{run.id}/review-checkpoints/{checkpoint.id}/{decision}/",
            headers=other,
            json={"expected_checkpoint_revision": checkpoint.revision},
        )
        assert response.status_code == 404, response.text
    assert (
        await client.get(base + f"runs/{run.id}/", headers=bearer)
    ).status_code == 200


async def test_same_idempotency_key_is_independent_per_service_principal(
    client,
    published,
    bearer,
    flows_enabled,
    provider,
):
    keys = [
        await _service_key(client, bearer, space_id=published["space_id"])
        for _ in range(2)
    ]
    url = f"/api/v1/flows/{published['flow'].id}/runs/"
    ids = []
    for key in keys:
        headers = {"X-API-Key": key, "Idempotency-Key": "shared-request-1"}
        first = await client.post(
            url, headers=headers, json={"values": {"topic": "private"}}
        )
        assert first.status_code == 201, first.text
        replay = await client.post(
            url, headers=headers, json={"values": {"topic": "private"}}
        )
        assert replay.json()["id"] == first.json()["id"]
        ids.append(first.json()["id"])
    assert len(set(ids)) == 2
    assert (
        await client.get(url + ids[0] + "/", headers={"X-API-Key": keys[1]})
    ).status_code == 404


async def test_stale_editor_cannot_overwrite_a_newer_revision(
    client,
    published,
    bearer,
    second_editor,
    flows_enabled,
):
    url = f"/api/v1/flows/{published['draft'].id}/"
    for headers in (bearer, second_editor["bearer"]):
        assert (
            await client.post(url + "edit-mode/", headers=headers)
        ).status_code == 200
    first = await client.patch(
        url, headers=bearer, json={"name": "Newer", "expected_revision": 1}
    )
    assert first.status_code == 200
    stale = await client.patch(
        url,
        headers=second_editor["bearer"],
        json={"name": "Stale", "expected_revision": 1},
    )
    assert stale.status_code == 409 and stale.json()["code"] == "flow_revision_conflict"
    assert (await client.get(url, headers=bearer)).json()["name"] == "Newer"


async def test_manual_publish_unpublish_and_republish_keep_version_numbers(
    client,
    published,
    bearer,
    flows_enabled,
):
    base = f"/api/v1/flows/{published['draft'].id}/"
    body = {"expected_revision": 1}
    first = await client.post(base + "publish/", headers=bearer, json=body)
    assert first.status_code == 200 and first.json()["published_version"] == 1
    assert (
        await client.post(base + "unpublish/", headers=bearer, json=body)
    ).status_code == 200
    assert (
        await client.post(
            base + "runs/", headers=bearer, json={"values": {"topic": "x"}}
        )
    ).status_code == 400
    again = await client.post(base + "publish/", headers=bearer, json=body)
    assert again.status_code == 200 and again.json()["published_version"] == 2
    key = await _service_key(client, bearer, space_id=published["space_id"])
    assert (
        await client.post(base + "unpublish/", headers={"X-API-Key": key}, json=body)
    ).status_code == 403


@pytest.mark.parametrize("retire", [False, True])
async def test_expired_or_retired_runs_terminalize_once_with_a_durable_audit(
    db_container,
    published,
    provider,
    monkeypatch,
    retire,
):
    monkeypatch.setattr(
        AuditService, "_should_log_action", AsyncMock(return_value=True)
    )
    async with db_container() as container:
        run = await _paused(container, published["flow"])
        checkpoint = run.review_checkpoint
        assert checkpoint is not None
        if retire:
            await container.flow_service().delete_flow(run.flow_id)
        else:
            await container.session().execute(
                sa.update(FlowRunReviewCheckpoints)
                .where(FlowRunReviewCheckpoints.id == checkpoint.id)
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        with pytest.raises((BadRequestException, NotFoundException)) as caught:
            await container.flow_run_service().approve_checkpoint(
                run.id, checkpoint.id, expected_revision=1
            )
        assert caught.value is not None
    # Exercise the actual cron owner with a session outside an HTTP transaction.
    async with sessionmanager.session() as session:
        with container.session.override(providers.Object(session)):
            await maintain_flow_run_lifecycle.__wrapped__(container=container)
            await maintain_flow_run_lifecycle.__wrapped__(container=container)
    async with db_container() as container:
        finished = await container.flow_run_service().get_run(run.id)
        assert finished.status == (
            FlowRunStatus.CANCELLED if retire else FlowRunStatus.FAILED
        )
        assert finished.error.code == (
            "flow_deleted" if retire else "flow_review_expired"
        )
        decision = await container.flow_repo().get_checkpoint(checkpoint.id, run.id)
        assert decision.state == ("cancelled" if retire else "expired")
        rows = (
            (
                await container.session().execute(
                    sa.select(AuditLog).where(
                        AuditLog.tenant_id == finished.tenant_id,
                        AuditLog.entity_id == run.id,
                        AuditLog.action
                        == ("flow_run_cancelled" if retire else "flow_run_failed"),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].log_metadata["extra"]["flow_id"] == str(run.flow_id)


async def test_published_default_model_stays_pinned_after_default_changes(
    db_container,
    published,
    completion_model_factory,
    provider,
):
    from eneo.database.tables.ai_models_table import CompletionModels
    from eneo.database.tables.spaces_table import SpacesCompletionModels

    async with db_container() as container:
        definition = published["flow"].definition.model_copy(deep=True)
        original_id = definition.steps[0].model_id
        definition.steps[0].model_id = None
        service = container.flow_service()
        await service.update_flow(published["flow"].id, definition=definition)
        await service.publish_flow(published["flow"].id)
        next_model = await completion_model_factory(
            container.session(), "new-default", is_default=True
        )
        container.session().add(
            SpacesCompletionModels(
                space_id=published["space_id"], completion_model_id=next_model.id
            )
        )
        await container.session().execute(
            sa.update(CompletionModels)
            .where(CompletionModels.id == original_id)
            .values(is_default=False)
        )
    async with db_container() as container:
        runs = container.flow_run_service()
        run = await runs.create_run(
            published["flow"].id, values={"topic": "x"}, files={}
        )
        await runs.execute_run(run.id)
        assert (await runs.get_run(run.id)).status == FlowRunStatus.COMPLETED
        assert provider.calls[-1]["model_id"] == original_id


async def test_terminal_transition_rolls_back_when_audit_cannot_be_written(
    db_container,
    published,
    provider,
    monkeypatch,
):
    from eneo.flows.lifecycle import finish_run

    async with db_container() as container:
        run = await container.flow_run_service().create_run(
            published["flow"].id, values={"topic": "x"}, files={}
        )
    monkeypatch.setattr(
        AuditService, "log", AsyncMock(side_effect=RuntimeError("audit unavailable"))
    )
    with pytest.raises(RuntimeError, match="audit unavailable"):
        async with db_container() as container:
            await finish_run(
                container.flow_repo(),
                container.audit_service(),
                run.id,
                run.tenant_id,
                FlowRunStatus.CANCELLED,
            )
    async with db_container() as container:
        assert (
            await container.flow_run_service().get_run(run.id)
        ).status == FlowRunStatus.QUEUED


async def test_approved_review_that_expires_in_queue_cannot_resume_execution(
    db_container,
    published,
    provider,
):
    async with db_container() as container:
        run = await _paused(container, published["flow"])
        checkpoint = run.review_checkpoint
        assert checkpoint is not None
        runs = container.flow_run_service()
        await runs.approve_checkpoint(
            run.id, checkpoint.id, expected_revision=checkpoint.revision, resume=True
        )
        await container.session().execute(
            sa.update(FlowRunReviewCheckpoints)
            .where(
                FlowRunReviewCheckpoints.id == checkpoint.id,
                FlowRunReviewCheckpoints.tenant_id == run.tenant_id,
            )
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        calls = len(provider.calls)
        await runs.execute_run(run.id)
        failed = await runs.get_run(run.id)
        assert failed.status == FlowRunStatus.FAILED
        assert failed.error.code == "flow_review_expired"
        assert len(provider.calls) == calls
        decision = await container.flow_repo().get_checkpoint(checkpoint.id, run.id)
        assert decision.state == "expired"


async def test_model_configuration_drift_is_refused_before_any_provider_call(
    db_container,
    published,
    provider,
):
    from eneo.database.tables.ai_models_table import CompletionModels

    async with db_container() as container:
        model_id = published["flow"].definition.steps[0].model_id
        await container.session().execute(
            sa.update(CompletionModels)
            .where(CompletionModels.id == model_id)
            .values(deployment_name="changed-after-publish")
        )
        with pytest.raises(BadRequestException, match="changed"):
            await container.flow_run_service().create_run(
                published["flow"].id, values={"topic": "x"}, files={}
            )
        assert provider.calls == []


async def test_viewer_can_review_own_run_and_admin_can_operate_it(
    client,
    published,
    second_editor,
    bearer,
    flows_enabled,
    db_container,
    provider,
):
    from eneo.database.tables.spaces_table import SpacesUsers

    async with db_container() as container:
        await _paused(container, published["flow"])
        await container.session().execute(
            sa.update(SpacesUsers)
            .where(
                SpacesUsers.space_id == published["space_id"],
                SpacesUsers.user_id == second_editor["user"].id,
            )
            .values(role="viewer")
        )
    base = f"/api/v1/flows/{published['flow'].id}/runs/"
    own = await client.post(
        base, headers=second_editor["bearer"], json={"values": {"topic": "mine"}}
    )
    assert own.status_code == 201, own.text
    async with db_container() as container:
        await container.flow_run_service().execute_run(own.json()["id"])
    result = await client.get(
        base + own.json()["id"] + "/", headers=second_editor["bearer"]
    )
    assert result.status_code == 200
    checkpoint = result.json()["review_checkpoint"]
    assert checkpoint is not None
    assert (
        await client.get(base + own.json()["id"] + "/", headers=bearer)
    ).status_code == 200
    approved = await client.post(
        base + own.json()["id"] + f"/review-checkpoints/{checkpoint['id']}/approve/",
        headers=second_editor["bearer"],
        json={"expected_checkpoint_revision": checkpoint["revision"]},
    )
    assert approved.status_code == 200, approved.text


async def test_service_cannot_attach_another_keys_runtime_upload(
    client,
    published,
    bearer,
    flows_enabled,
    db_container,
    provider,
):
    from eneo.flows.definition import FormField

    async with db_container() as container:
        definition = published["flow"].definition.model_copy(deep=True)
        definition.form_fields.append(
            FormField(key="source", label="Source", type="file", required=False)
        )
        await container.flow_service().update_flow(
            published["flow"].id, definition=definition
        )
        await container.flow_service().publish_flow(published["flow"].id)
    keys = [
        await _service_key(client, bearer, space_id=published["space_id"])
        for _ in range(2)
    ]
    base = f"/api/v1/flows/{published['flow'].id}/"
    uploaded = await client.post(
        base + "runtime-files/",
        headers={"X-API-Key": keys[0]},
        files={"upload_file": ("private.txt", b"private", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    body = {"values": {"topic": "x"}, "files": {"source": [uploaded.json()["id"]]}}
    forbidden = await client.post(
        base + "runs/", headers={"X-API-Key": keys[1]}, json=body
    )
    assert forbidden.status_code == 400, forbidden.text
    own = await client.post(base + "runs/", headers={"X-API-Key": keys[0]}, json=body)
    assert own.status_code == 201, own.text


async def test_terminal_audit_is_durable_and_not_duplicated(
    db_container, published, provider, monkeypatch
):
    monkeypatch.setattr(
        AuditService, "_should_log_action", AsyncMock(return_value=True)
    )
    async with db_container() as container:
        runs = container.flow_run_service()
        run = await runs.create_run(
            published["flow"].id, values={"topic": "x"}, files={}
        )
        await runs.execute_run(run.id)
        await runs.execute_run(run.id)
        completed = await runs.get_run(run.id)
        assert completed.status == FlowRunStatus.COMPLETED
    async with db_container() as container:
        rows = (
            (
                await container.session().execute(
                    sa.select(AuditLog).where(
                        AuditLog.tenant_id == completed.tenant_id,
                        AuditLog.entity_id == run.id,
                        AuditLog.action == "flow_run_completed",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
