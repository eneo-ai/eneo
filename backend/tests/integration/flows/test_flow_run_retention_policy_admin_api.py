from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.flow_tables import (
    FlowRunAuditOutbox,
    FlowRuns,
    FlowRunWebhookDeliveries,
    Flows,
    FlowStepAttempts,
    FlowVersions,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_admin_explicit_purge_defaults_to_preview_and_audits_deletion(
    client, admin_token, admin_user, published_flow_ids, db_container
) -> None:
    _, flow_id = published_flow_ids
    old = datetime.now(timezone.utc) - timedelta(days=3)
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.update(Flows)
            .where(Flows.id == flow_id)
            .values(
                flow_run_history_retention_mode="preserve",
                flow_run_history_retention_days=1,
            )
        )
        run = FlowRuns(
            flow_id=flow_id,
            flow_version=1,
            principal_type="user",
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            trace_id=uuid4(),
            status="completed",
            started_at=old,
            finished_at=old,
            created_at=old,
            updated_at=old,
        )
        session.add(run)
        await session.flush()
        run_id = run.id

    path = "/api/v1/settings/flow-run-retention-policy/purge"
    headers = {"Authorization": f"Bearer {admin_token}"}
    preview = await client.post(path, json={}, headers=headers)
    assert preview.status_code == 200, preview.text
    assert preview.json() == {
        "dry_run": True,
        "scope": "organization",
        "candidate_count": 1,
        "purged_count": 0,
        "purged_run_ids": [],
        "blocked": {
            "undelivered_audit": 0,
            "unresolved_webhook": 0,
            "review_required": 0,
            "counted_runs": 1,
            "complete": True,
        },
    }
    async with db_container() as container:
        assert await container.session().get(FlowRuns, run_id) is not None
        assert (
            await container.session().scalar(
                sa.select(sa.func.count(AuditLog.id)).where(
                    AuditLog.action == "flow_run_history_purged"
                )
            )
            == 0
        )

    response = await client.post(path, json={"dry_run": False}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == {
        **preview.json(),
        "dry_run": False,
        "purged_count": 1,
        "purged_run_ids": [str(run_id)],
    }
    async with db_container() as container:
        assert await container.session().get(FlowRuns, run_id) is None
        audit = (
            await container.session().scalars(
                sa.select(AuditLog).where(AuditLog.action == "flow_run_history_purged")
            )
        ).one()
        assert audit.tenant_id == admin_user.tenant_id
        assert audit.log_metadata == {
            "scope": "organization",
            "scope_id": str(admin_user.tenant_id),
            "tenant_id": str(admin_user.tenant_id),
            "space_id": None,
            "flow_id": None,
            "limit": 100,
            "purged_count": 1,
            "purged_run_ids": [str(run_id)],
            "blocked": preview.json()["blocked"],
        }


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


@pytest.fixture
async def regular_token(
    db_container,
    patch_auth_service_jwt,
    user_factory,
    admin_user,
):
    async with db_container() as container:
        regular_user = await user_factory(
            container.session(),
            tenant_id=admin_user.tenant_id,
        )
        return container.auth_service().create_access_token_for_user(regular_user)


@pytest.fixture
async def published_flow_ids(db_container, admin_user) -> tuple[object, object]:
    async with db_container() as container:
        session = container.session()
        organization_space_id = await session.scalar(
            sa.select(Spaces.id).where(
                Spaces.tenant_id == admin_user.tenant_id,
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_(None),
            )
        )
        assert organization_space_id is not None
        space = Spaces(
            name=f"Retention policy Space {uuid4()}",
            description="Flow retention is independent from conversation retention.",
            tenant_id=admin_user.tenant_id,
            user_id=None,
            tenant_space_id=organization_space_id,
            security_classification_id=None,
            data_retention_days=7,
            flow_run_history_retention_mode=None,
            flow_run_history_retention_days=None,
        )
        session.add(space)
        await session.flush()
        flow = Flows(
            name=f"Published retention policy Flow {uuid4()}",
            description="Published definition remains immutable.",
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            created_by_user_id=admin_user.id,
            owner_user_id=admin_user.id,
            published_version=None,
            metadata_json=None,
            flow_run_history_retention_mode=None,
            flow_run_history_retention_days=None,
        )
        session.add(flow)
        await session.flush()
        session.add(
            FlowVersions(
                flow_id=flow.id,
                version=1,
                tenant_id=admin_user.tenant_id,
                definition_checksum=f"retention-policy-{uuid4()}",
                definition_json={"schema_version": 1, "steps": []},
            )
        )
        await session.flush()
        flow.published_version = 1
        await session.flush()
        return space.id, flow.id


async def test_admin_replaces_and_clears_complete_hierarchical_policies(
    client,
    admin_token,
    regular_token,
    published_flow_ids,
    db_container,
    admin_user,
) -> None:
    space_id, flow_id = published_flow_ids
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    regular_headers = {"Authorization": f"Bearer {regular_token}"}
    root_path = "/api/v1/settings/flow-run-retention-policy"
    space_path = f"{root_path}/spaces/{space_id}"
    flow_path = f"{root_path}/flows/{flow_id}"

    organization_response = await client.put(
        root_path,
        json={"policy": {"mode": "preserve", "days": 30}},
        headers=admin_headers,
    )
    assert organization_response.status_code == 200, organization_response.text
    unchanged_organization_response = await client.put(
        root_path,
        json={"policy": {"mode": "preserve", "days": 30}},
        headers=admin_headers,
    )
    assert unchanged_organization_response.status_code == 200

    space_response = await client.put(
        space_path,
        json={"policy": {"mode": "review_required", "days": 60}},
        headers=admin_headers,
    )
    assert space_response.status_code == 200, space_response.text

    flow_response = await client.put(
        flow_path,
        json={"policy": {"mode": "preserve", "days": 90}},
        headers=admin_headers,
    )
    assert flow_response.status_code == 200, flow_response.text
    flow_settings = flow_response.json()
    assert flow_settings["scope"] == "flow"
    assert flow_settings["scope_id"] == str(flow_id)
    assert flow_settings["local_policy"] == {"mode": "preserve", "days": 90}
    assert flow_settings["inherited_policy"] == {
        "mode": "review_required",
        "days": 60,
    }
    assert flow_settings["effective"] == {
        "state": "configured",
        "mode": "preserve",
        "effective_days": 90,
        "source": "flow",
        "contributors": {
            "organization": {"mode": "preserve", "days": 30},
            "space": {"mode": "review_required", "days": 60},
            "flow": {"mode": "preserve", "days": 90},
        },
    }

    old = datetime.now(timezone.utc) - timedelta(days=100)
    async with db_container() as container:
        session = container.session()
        inherited_flow = Flows(
            name=f"Inherited retention Flow {uuid4()}",
            description="Uses the Space review policy.",
            tenant_id=admin_user.tenant_id,
            space_id=space_id,
            created_by_user_id=admin_user.id,
            owner_user_id=admin_user.id,
            published_version=None,
            metadata_json=None,
            flow_run_history_retention_mode=None,
            flow_run_history_retention_days=None,
        )
        session.add(inherited_flow)
        await session.flush()
        session.add(
            FlowVersions(
                flow_id=inherited_flow.id,
                version=1,
                tenant_id=admin_user.tenant_id,
                definition_checksum=f"retention-review-{uuid4()}",
                definition_json={"schema_version": 1, "steps": []},
            )
        )
        await session.flush()
        inherited_flow.published_version = 1
        review_run = FlowRuns(
            flow_id=inherited_flow.id,
            flow_version=1,
            principal_type="user",
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            trace_id=uuid4(),
            status="completed",
            started_at=old,
            finished_at=old,
            input_payload_json={"must_not": "appear in review queue"},
            output_payload_json={"must_not": "appear in review queue"},
            created_at=old,
            updated_at=old,
        )
        preserved_run = FlowRuns(
            flow_id=flow_id,
            flow_version=1,
            principal_type="user",
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            trace_id=uuid4(),
            status="completed",
            started_at=old,
            finished_at=old,
            input_payload_json={"must_not": "appear in review queue"},
            output_payload_json={"must_not": "appear in review queue"},
            created_at=old,
            updated_at=old,
        )
        session.add_all([review_run, preserved_run])
        await session.flush()
        review_run_id = review_run.id
        preserved_run_id = preserved_run.id
        inherited_flow_id = inherited_flow.id

    queue_response = await client.get(
        f"{space_path}/review-queue?limit=10",
        headers=admin_headers,
    )
    assert queue_response.status_code == 200, queue_response.text
    queue = queue_response.json()
    assert queue["count"] == 1
    assert queue["has_more"] is False
    assert len(queue["items"]) == 1
    assert queue["items"][0]["run_id"] == str(review_run_id)
    assert queue["items"][0]["flow_id"] == str(inherited_flow_id)
    assert queue["items"][0]["effective_policy"] == {
        "mode": "review_required",
        "days": 60,
    }
    assert queue["items"][0]["policy_source"] == "space"
    assert "input_payload_json" not in queue["items"][0]
    assert "output_payload_json" not in queue["items"][0]

    clear_response = await client.put(
        flow_path,
        json={"policy": None},
        headers=admin_headers,
    )
    assert clear_response.status_code == 200, clear_response.text
    cleared = clear_response.json()
    assert cleared["local_policy"] is None
    assert cleared["effective"]["mode"] == "review_required"
    assert cleared["effective"]["effective_days"] == 60
    assert cleared["effective"]["source"] == "space"

    inherited_queue_response = await client.get(
        f"{flow_path}/review-queue?limit=10",
        headers=admin_headers,
    )
    assert inherited_queue_response.status_code == 200, inherited_queue_response.text
    inherited_queue = inherited_queue_response.json()
    assert [item["run_id"] for item in inherited_queue["items"]] == [
        str(preserved_run_id)
    ]

    forbidden_get = await client.get(flow_path, headers=regular_headers)
    forbidden_put = await client.put(
        flow_path,
        json={"policy": {"mode": "preserve", "days": 10}},
        headers=regular_headers,
    )
    assert forbidden_get.status_code == 403, forbidden_get.text
    assert forbidden_put.status_code == 403, forbidden_put.text

    async with db_container() as container:
        audit_rows = list(
            (
                await container.session().execute(
                    sa.select(
                        AuditLog.actor_id,
                        AuditLog.entity_type,
                        AuditLog.entity_id,
                        AuditLog.log_metadata,
                    )
                    .where(AuditLog.tenant_id == admin_user.tenant_id)
                    .where(AuditLog.action == "flow_run_retention_policy_changed")
                    .order_by(AuditLog.timestamp.asc())
                )
            ).all()
        )
    assert len(audit_rows) == 4
    assert all(row.actor_id == admin_user.id for row in audit_rows)
    assert audit_rows[-1].entity_type == "flow"
    assert audit_rows[-1].entity_id == flow_id
    assert audit_rows[-1].log_metadata == {
        "scope": "flow",
        "scope_id": str(flow_id),
        "previous_local_policy": {"mode": "preserve", "days": 90},
        "new_local_policy": None,
        "effective_policy": {"mode": "review_required", "days": 60},
        "effective_source": "space",
    }


async def test_partial_or_automatic_policy_is_rejected_without_mutation(
    client,
    admin_token,
    published_flow_ids,
) -> None:
    _, flow_id = published_flow_ids
    headers = {"Authorization": f"Bearer {admin_token}"}
    path = f"/api/v1/settings/flow-run-retention-policy/flows/{flow_id}"

    for policy in ({"days": 30}, {"mode": "automatic", "days": 30}):
        response = await client.put(path, json={"policy": policy}, headers=headers)
        assert response.status_code == 422, response.text

    current = await client.get(path, headers=headers)
    assert current.status_code == 200, current.text
    assert current.json()["local_policy"] is None


async def test_admin_discovers_non_member_spaces_and_flows_for_retention(
    client,
    admin_token,
    regular_token,
    published_flow_ids,
    db_container,
    admin_user,
) -> None:
    space_id, flow_id = published_flow_ids
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    regular_headers = {"Authorization": f"Bearer {regular_token}"}
    root_path = "/api/v1/settings/flow-run-retention-policy/targets/spaces"

    spaces_response = await client.get(
        f"{root_path}?limit=200&offset=0",
        headers=admin_headers,
    )
    assert spaces_response.status_code == 200, spaces_response.text
    assert str(space_id) in {item["id"] for item in spaces_response.json()["items"]}

    flows_response = await client.get(
        f"{root_path}/{space_id}/flows?limit=200&offset=0",
        headers=admin_headers,
    )
    assert flows_response.status_code == 200, flows_response.text
    assert flows_response.json() == {
        "items": [
            {
                "id": str(flow_id),
                "space_id": str(space_id),
                "name": flows_response.json()["items"][0]["name"],
            }
        ],
        "count": 1,
        "has_more": False,
    }

    forbidden = await client.get(root_path, headers=regular_headers)
    assert forbidden.status_code == 403, forbidden.text

    async with db_container() as container:
        personal_space_id = await container.session().scalar(
            sa.select(Spaces.id).where(
                Spaces.tenant_id == admin_user.tenant_id,
                Spaces.user_id == admin_user.id,
            )
        )
        if personal_space_id is None:
            personal_space = Spaces(
                name=f"Personal retention target {uuid4()}",
                tenant_id=admin_user.tenant_id,
                user_id=admin_user.id,
            )
            container.session().add(personal_space)
            await container.session().flush()
            personal_space_id = personal_space.id

    personal_flow_targets = await client.get(
        f"{root_path}/{personal_space_id}/flows",
        headers=admin_headers,
    )
    assert personal_flow_targets.status_code == 404, personal_flow_targets.text


async def test_review_required_run_is_listed_but_never_selected_for_purge(
    client,
    admin_token,
    published_flow_ids,
    db_container,
    admin_user,
) -> None:
    _, flow_id = published_flow_ids
    headers = {"Authorization": f"Bearer {admin_token}"}
    root_path = "/api/v1/settings/flow-run-retention-policy"
    flow_path = f"{root_path}/flows/{flow_id}"
    policy_response = await client.put(
        flow_path,
        json={"policy": {"mode": "review_required", "days": 1}},
        headers=headers,
    )
    assert policy_response.status_code == 200, policy_response.text

    old = datetime.now(timezone.utc) - timedelta(days=3)
    async with db_container() as container:
        first_run = FlowRuns(
            flow_id=flow_id,
            flow_version=1,
            principal_type="user",
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            trace_id=uuid4(),
            status="completed",
            started_at=old,
            finished_at=old,
            input_payload_json={"sensitive": "input"},
            output_payload_json={"sensitive": "output"},
            created_at=old,
            updated_at=old,
        )
        second_anchor = old + timedelta(hours=1)
        second_run = FlowRuns(
            flow_id=flow_id,
            flow_version=1,
            principal_type="user",
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            trace_id=uuid4(),
            status="completed",
            started_at=second_anchor,
            finished_at=second_anchor,
            input_payload_json={"sensitive": "second input"},
            output_payload_json={"sensitive": "second output"},
            created_at=second_anchor,
            updated_at=second_anchor,
        )
        container.session().add_all([first_run, second_run])
        await container.session().flush()
        first_run_id = first_run.id
        second_run_id = second_run.id

    first_page_response = await client.get(
        f"{flow_path}/review-queue?limit=1",
        headers=headers,
    )
    assert first_page_response.status_code == 200, first_page_response.text
    first_page = first_page_response.json()
    assert [item["run_id"] for item in first_page["items"]] == [str(first_run_id)]
    assert first_page["has_more"] is True
    assert first_page["next_cursor"]

    second_page_response = await client.get(
        f"{flow_path}/review-queue?limit=1&cursor={first_page['next_cursor']}",
        headers=headers,
    )
    assert second_page_response.status_code == 200, second_page_response.text
    second_page = second_page_response.json()
    assert [item["run_id"] for item in second_page["items"]] == [str(second_run_id)]
    assert second_page["has_more"] is False
    assert second_page["next_cursor"] is None

    invalid_cursor = await client.get(
        f"{flow_path}/review-queue?cursor=invalid",
        headers=headers,
    )
    assert invalid_cursor.status_code == 400, invalid_cursor.text
    assert invalid_cursor.json()["code"] == "invalid_flow_retention_review_cursor"

    oversized_cursor = await client.get(
        f"{flow_path}/review-queue?cursor={'x' * 513}",
        headers=headers,
    )
    assert oversized_cursor.status_code == 422, oversized_cursor.text

    async with db_container() as container:
        purge_result = (
            await container.data_retention_service().purge_old_flow_run_history_batch(
                now=datetime.now(timezone.utc),
                limit=10,
            )
        )
        assert purge_result.counts.flow_runs_considered == 0
        assert await container.session().get(FlowRuns, first_run_id) is not None
        assert await container.session().get(FlowRuns, second_run_id) is not None


async def test_required_audit_failure_rolls_back_policy_change(
    client,
    admin_token,
    published_flow_ids,
    db_container,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, flow_id = published_flow_ids
    headers = {"Authorization": f"Bearer {admin_token}"}
    path = f"/api/v1/settings/flow-run-retention-policy/flows/{flow_id}"

    async def fail_audit_insert(
        _repository: AuditLogRepositoryImpl,
        _audit_log: object,
    ) -> object:
        raise RuntimeError("forced retention audit failure")

    monkeypatch.setattr(AuditLogRepositoryImpl, "create", fail_audit_insert)

    with pytest.raises(RuntimeError, match="forced retention audit failure"):
        await client.put(
            path,
            json={"policy": {"mode": "preserve", "days": 30}},
            headers=headers,
        )

    async with db_container() as container:
        stored = (
            await container.session().execute(
                sa.select(
                    Flows.flow_run_history_retention_mode,
                    Flows.flow_run_history_retention_days,
                ).where(Flows.id == flow_id)
            )
        ).one()
    assert stored == (None, None)


async def test_foreign_tenant_targets_are_not_visible_or_mutable(
    client,
    admin_token,
    admin_user,
    db_container,
) -> None:
    async with db_container() as container:
        session = container.session()
        foreign_tenant = Tenants(
            name=f"Foreign retention tenant {uuid4()}",
            state="active",
            quota_limit=1_000_000,
        )
        session.add(foreign_tenant)
        await session.flush()
        foreign_space = Spaces(
            name=f"Foreign retention Space {uuid4()}",
            description=None,
            tenant_id=foreign_tenant.id,
            user_id=None,
            tenant_space_id=None,
            security_classification_id=None,
            data_retention_days=None,
            flow_run_history_retention_mode=None,
            flow_run_history_retention_days=None,
        )
        session.add(foreign_space)
        await session.flush()
        foreign_flow = Flows(
            name=f"Foreign retention Flow {uuid4()}",
            description=None,
            tenant_id=foreign_tenant.id,
            space_id=foreign_space.id,
            created_by_user_id=None,
            owner_user_id=None,
            published_version=None,
            metadata_json=None,
            flow_run_history_retention_mode=None,
            flow_run_history_retention_days=None,
        )
        session.add(foreign_flow)
        await session.flush()
        foreign_space_id = foreign_space.id
        foreign_flow_id = foreign_flow.id

    headers = {"Authorization": f"Bearer {admin_token}"}
    root_path = "/api/v1/settings/flow-run-retention-policy"
    paths = [
        f"{root_path}/spaces/{foreign_space_id}",
        f"{root_path}/spaces/{foreign_space_id}/review-queue",
        f"{root_path}/flows/{foreign_flow_id}",
        f"{root_path}/flows/{foreign_flow_id}/review-queue",
        f"{root_path}/targets/spaces/{foreign_space_id}/flows",
    ]
    for path in paths:
        response = await client.get(path, headers=headers)
        assert response.status_code == 404, (path, response.text)

    for path in (
        f"{root_path}/spaces/{foreign_space_id}",
        f"{root_path}/flows/{foreign_flow_id}",
    ):
        response = await client.put(
            path,
            json={"policy": {"mode": "preserve", "days": 30}},
            headers=headers,
        )
        assert response.status_code == 404, (path, response.text)

    targets_response = await client.get(
        f"{root_path}/targets/spaces?limit=200&offset=0",
        headers=headers,
    )
    assert targets_response.status_code == 200, targets_response.text
    assert str(foreign_space_id) not in {
        item["id"] for item in targets_response.json()["items"]
    }

    async with db_container() as container:
        foreign_policy = (
            await container.session().execute(
                sa.select(
                    Flows.flow_run_history_retention_mode,
                    Flows.flow_run_history_retention_days,
                ).where(Flows.id == foreign_flow_id)
            )
        ).one()
        new_audits = await container.session().scalar(
            sa.select(sa.func.count(AuditLog.id))
            .where(AuditLog.tenant_id == admin_user.tenant_id)
            .where(AuditLog.action == "flow_run_retention_policy_changed")
        )
    assert foreign_policy == (None, None)
    assert new_audits == 0


@pytest.fixture
async def purge_history(db_container, admin_user, published_flow_ids, user_factory):
    space_id, flow_id = published_flow_ids
    old = datetime.now(timezone.utc) - timedelta(days=3)
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == admin_user.tenant_id)
            .values(
                flow_run_history_retention_mode="preserve",
                flow_run_history_retention_days=1,
            )
        )

        async def add_flow(tenant_id, target_space_id, mode=None):
            flow = Flows(
                name=f"Purge scope {uuid4()}",
                tenant_id=tenant_id,
                space_id=target_space_id,
                flow_run_history_retention_mode=mode,
                flow_run_history_retention_days=1 if mode else None,
            )
            session.add(flow)
            await session.flush()
            session.add(
                FlowVersions(
                    flow_id=flow.id,
                    version=1,
                    tenant_id=tenant_id,
                    definition_checksum=str(uuid4()),
                    definition_json={"schema_version": 1, "steps": []},
                )
            )
            await session.flush()
            return flow.id

        async def add_run(
            target_flow_id,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            status="completed",
        ):
            run = FlowRuns(
                flow_id=target_flow_id,
                flow_version=1,
                tenant_id=tenant_id,
                principal_type="user",
                principal_user_id=user_id,
                trace_id=uuid4(),
                status=status,
                started_at=old,
                finished_at=old if status == "completed" else None,
                created_at=old,
                updated_at=old,
            )
            session.add(run)
            await session.flush()
            return run

        first = await add_run(flow_id)
        second = await add_run(flow_id)
        sibling_flow_id = await add_flow(admin_user.tenant_id, space_id)
        sibling = await add_run(sibling_flow_id)
        parent_space_id = await session.scalar(
            sa.select(Spaces.tenant_space_id).where(Spaces.id == space_id)
        )
        other_space = Spaces(
            name="Other purge scope",
            tenant_id=admin_user.tenant_id,
            tenant_space_id=parent_space_id,
        )
        session.add(other_space)
        await session.flush()
        outside_flow_id = await add_flow(admin_user.tenant_id, other_space.id)
        outside = await add_run(outside_flow_id)
        review_flow_id = await add_flow(
            admin_user.tenant_id, space_id, "review_required"
        )
        review = await add_run(review_flow_id)
        running = await add_run(flow_id, status="running")
        audit_run = await add_run(flow_id)
        session.add(
            FlowRunAuditOutbox(
                tenant_id=admin_user.tenant_id,
                flow_id=flow_id,
                flow_run_id=audit_run.id,
                run_revision=1,
                description="flow_run_completed:executor_completed",
                action="flow_run_completed",
                entity_type="flow_run",
                entity_id=audit_run.id,
                actor_id=admin_user.id,
                actor_type="user",
                source="executor_completed",
                target_status="completed",
                delivery_status="pending",
            )
        )
        webhook_run = await add_run(flow_id)
        step_id = uuid4()
        session.add(
            FlowStepAttempts(
                flow_run_id=webhook_run.id,
                flow_id=flow_id,
                tenant_id=admin_user.tenant_id,
                step_id=step_id,
                step_order=1,
                attempt_no=1,
                status="completed",
                started_at=old,
                finished_at=old,
            )
        )
        await session.flush()
        session.add(
            FlowRunWebhookDeliveries(
                tenant_id=admin_user.tenant_id,
                flow_id=flow_id,
                flow_run_id=webhook_run.id,
                step_id=step_id,
                step_order=1,
                attempt_no=1,
                idempotency_key=str(uuid4()),
                payload_ref="payload",
                delivery_status="pending",
            )
        )
        foreign_tenant = Tenants(
            name=f"Purge isolation {uuid4()}",
            state="active",
            quota_limit=1_000_000,
            flow_run_history_retention_mode="preserve",
            flow_run_history_retention_days=1,
        )
        session.add(foreign_tenant)
        await session.flush()
        foreign_user = await user_factory(session, tenant_id=foreign_tenant.id)
        foreign_space = Spaces(name="Foreign purge scope", tenant_id=foreign_tenant.id)
        session.add(foreign_space)
        await session.flush()
        foreign_flow_id = await add_flow(foreign_tenant.id, foreign_space.id)
        foreign = await add_run(foreign_flow_id, foreign_tenant.id, foreign_user.id)
        foreign_running = await add_run(
            foreign_flow_id, foreign_tenant.id, foreign_user.id, status="running"
        )
        await session.flush()
        return {
            "space_id": space_id,
            "flow_id": flow_id,
            "foreign_space_id": foreign_space.id,
            "foreign_flow_id": foreign_flow_id,
            "eligible": {
                "organization": {first.id, second.id, sibling.id, outside.id},
                "space": {first.id, second.id, sibling.id},
                "flow": {first.id, second.id},
            },
            "retained": {
                review.id,
                running.id,
                audit_run.id,
                webhook_run.id,
                foreign.id,
                foreign_running.id,
            },
        }


@pytest.mark.parametrize("scope", ["organization", "space", "flow"])
async def test_purge_is_scoped_bounded_and_reports_blocked_runs(
    client, admin_token, db_container, purge_history, scope
):
    root = "/api/v1/settings/flow-run-retention-policy"
    suffix = (
        "" if scope == "organization" else f"/{scope}s/{purge_history[f'{scope}_id']}"
    )
    path = f"{root}{suffix}/purge"
    headers = {"Authorization": f"Bearer {admin_token}"}
    preview = await client.post(path, json={"limit": 1}, headers=headers)
    assert preview.status_code == 200, preview.text
    blocked = {
        "undelivered_audit": 1,
        "unresolved_webhook": 1,
        "review_required": 0 if scope == "flow" else 1,
        "counted_runs": {"organization": 7, "space": 6, "flow": 4}[scope],
        "complete": True,
    }
    assert preview.json()["candidate_count"] == 1
    assert preview.json()["blocked"] == blocked
    expected = purge_history["eligible"][scope]
    all_run_ids = purge_history["eligible"]["organization"] | purge_history["retained"]
    async with db_container() as container:
        stored = set((await container.session().scalars(sa.select(FlowRuns.id))).all())
        assert all_run_ids <= stored
    purged = set()
    for index in range(len(expected)):
        response = await client.post(
            path, json={"dry_run": False, "limit": 1}, headers=headers
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["scope"] == scope
        assert result["candidate_count"] == result["purged_count"] == 1
        assert result["blocked"] == {
            **blocked,
            "counted_runs": blocked["counted_runs"] - index,
        }
        purged.update(result["purged_run_ids"])
    assert purged == {str(run_id) for run_id in expected}
    empty = await client.post(path, json={"dry_run": False}, headers=headers)
    assert empty.status_code == 200, empty.text
    assert empty.json()["candidate_count"] == empty.json()["purged_count"] == 0
    assert empty.json()["blocked"] == {
        **blocked,
        "counted_runs": blocked["counted_runs"] - len(expected),
    }
    async with db_container() as container:
        stored = set((await container.session().scalars(sa.select(FlowRuns.id))).all())
        assert stored == all_run_ids - expected
        audits = (
            await container.session().scalars(
                sa.select(AuditLog).where(AuditLog.action == "flow_run_history_purged")
            )
        ).all()
        assert len(audits) == len(expected) + 1
        for audit in audits:
            assert audit.log_metadata["scope"] == scope
            assert audit.log_metadata["scope_id"] == str(
                audit.tenant_id
                if scope == "organization"
                else purge_history[f"{scope}_id"]
            )
            assert {
                key: value
                for key, value in audit.log_metadata["blocked"].items()
                if key != "counted_runs"
            } == {key: value for key, value in blocked.items() if key != "counted_runs"}
        assert {
            audit.log_metadata["blocked"]["counted_runs"] for audit in audits
        } == set(
            range(blocked["counted_runs"] - len(expected), blocked["counted_runs"] + 1)
        )


async def test_purge_requires_admin_and_hides_foreign_scopes(
    client, regular_token, admin_token, db_container, purge_history
):
    root = "/api/v1/settings/flow-run-retention-policy"
    for suffix in (
        "",
        f"/spaces/{purge_history['space_id']}",
        f"/flows/{purge_history['flow_id']}",
    ):
        response = await client.post(
            f"{root}{suffix}/purge",
            json={"dry_run": False},
            headers={"Authorization": f"Bearer {regular_token}"},
        )
        assert response.status_code == 403, response.text
    for scope in ("space", "flow"):
        response = await client.post(
            f"{root}/{scope}s/{purge_history[f'foreign_{scope}_id']}/purge",
            json={"dry_run": False},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404, response.text
    async with db_container() as container:
        assert (
            await container.session().scalar(
                sa.select(sa.func.count(AuditLog.id)).where(
                    AuditLog.action == "flow_run_history_purged"
                )
            )
            == 0
        )
        assert set(
            (await container.session().scalars(sa.select(FlowRuns.id))).all()
        ) == (purge_history["eligible"]["organization"] | purge_history["retained"])


async def test_purge_audit_failure_rolls_back_deleted_history(
    client, admin_token, db_container, purge_history, monkeypatch
):
    async def fail_audit_insert(_repository, _audit_log):
        raise RuntimeError("forced purge audit failure")

    monkeypatch.setattr(AuditLogRepositoryImpl, "create", fail_audit_insert)
    with pytest.raises(RuntimeError, match="forced purge audit failure"):
        await client.post(
            "/api/v1/settings/flow-run-retention-policy/purge",
            json={"dry_run": False},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    async with db_container() as container:
        assert set(
            (await container.session().scalars(sa.select(FlowRuns.id))).all()
        ) == (purge_history["eligible"]["organization"] | purge_history["retained"])
        assert (
            await container.session().scalar(
                sa.select(sa.func.count(AuditLog.id)).where(
                    AuditLog.action == "flow_run_history_purged"
                )
            )
            == 0
        )


async def test_concurrent_purges_audit_only_their_own_deleted_runs(
    db_container, purge_history
):
    async with db_container() as first_container:
        first = (
            await first_container.flow_run_retention_policy_service().purge_due_history(
                dry_run=False, limit=1
            )
        )
        async with db_container() as second_container:
            second = await second_container.flow_run_retention_policy_service().purge_due_history(
                dry_run=False, limit=1
            )
    assert first.purged_count == second.purged_count == 1
    assert set(first.purged_run_ids).isdisjoint(second.purged_run_ids)
    expected = set(first.purged_run_ids) | set(second.purged_run_ids)
    assert expected <= purge_history["eligible"]["organization"]
    async with db_container() as container:
        audits = (
            await container.session().scalars(
                sa.select(AuditLog).where(AuditLog.action == "flow_run_history_purged")
            )
        ).all()
        assert len(audits) == 2
        assert {
            run_id
            for audit in audits
            for run_id in audit.log_metadata["purged_run_ids"]
        } == {str(run_id) for run_id in expected}
        assert not expected & set(
            (await container.session().scalars(sa.select(FlowRuns.id))).all()
        )


@pytest.mark.parametrize("extra_review_run", [False, True])
async def test_purge_diagnostics_count_only_the_window_and_report_completeness(
    client, admin_token, admin_user, db_container, purge_history, extra_review_run
):
    old = datetime.now(timezone.utc) - timedelta(days=4)
    async with db_container() as container:
        session = container.session()
        session.add_all(
            [
                FlowRuns(
                    flow_id=purge_history["flow_id"],
                    flow_version=1,
                    tenant_id=admin_user.tenant_id,
                    principal_type="user",
                    principal_user_id=admin_user.id,
                    trace_id=uuid4(),
                    status="completed",
                    started_at=old,
                    finished_at=old,
                    created_at=old,
                    updated_at=old,
                )
                for _ in range(493)
            ]
        )
        if extra_review_run:
            review_flow_id = await session.scalar(
                sa.select(Flows.id).where(
                    Flows.tenant_id == admin_user.tenant_id,
                    Flows.flow_run_history_retention_mode == "review_required",
                )
            )
            newest = datetime.now(timezone.utc) - timedelta(days=2)
            session.add(
                FlowRuns(
                    flow_id=review_flow_id,
                    flow_version=1,
                    tenant_id=admin_user.tenant_id,
                    principal_type="user",
                    principal_user_id=admin_user.id,
                    trace_id=uuid4(),
                    status="completed",
                    started_at=newest,
                    finished_at=newest,
                    created_at=newest,
                    updated_at=newest,
                )
            )

    response = await client.post(
        "/api/v1/settings/flow-run-retention-policy/purge",
        json={"limit": 1},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["candidate_count"] == 1
    assert response.json()["blocked"] == {
        "undelivered_audit": 1,
        "unresolved_webhook": 1,
        "review_required": 1,
        "counted_runs": 500,
        "complete": not extra_review_run,
    }
