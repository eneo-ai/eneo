"""Sync-log HTTP authorization with real space policy and SQLite access queries."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers
from httpx import ASGITransport, AsyncClient

from eneo.authentication.auth_models import ApiKeyOwnership
from eneo.database.tables.integration_knowledge_spaces_table import (
    IntegrationKnowledgesSpaces,
)
from eneo.database.tables.integration_table import IntegrationKnowledge
from eneo.database.tables.spaces_table import Spaces, SpacesUserGroups, SpacesUsers
from eneo.database.tables.user_groups_table import UserGroups
from eneo.integration.domain.entities.sync_log import SyncLog
from eneo.integration.domain.repositories.sync_log_repo import SyncLogRepository
from eneo.main.container.container import Container
from eneo.roles.permissions import Permission
from eneo.spaces.space_repo import SpaceRepository
from eneo.users.user import UserGroupInDBRead


@pytest.fixture
def sync_log_database(integration_access):
    # Keep only columns used by the production access SELECTs. Their names and
    # types come from the real tables; unrelated PostgreSQL payloads are omitted.
    metadata = sa.MetaData()
    tables = {}
    for model, names in [
        (IntegrationKnowledge, ("id", "space_id", "tenant_id")),
        (IntegrationKnowledgesSpaces, ("integration_knowledge_id", "space_id")),
        (Spaces, ("id", "user_id", "tenant_space_id", "tenant_id")),
        (SpacesUsers, ("space_id", "user_id", "role")),
        (SpacesUserGroups, ("space_id", "user_group_id", "role")),
        (UserGroups, ("id", "tenant_id", "state")),
    ]:
        tables[model] = sa.Table(
            model.__table__.name,
            metadata,
            *[
                sa.Column(
                    name,
                    model.__table__.c[name].type,
                    primary_key=model.__table__.c[name].primary_key,
                )
                for name in names
            ],
        )
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    with engine.begin() as connection:
        session = AsyncMock()
        session.execute.side_effect = connection.execute
        repo = SpaceRepository(
            session=session,
            user=integration_access.user,
            factory=MagicMock(),
            file_content_loader=MagicMock(),
            completion_model_repo=MagicMock(),
            transcription_model_repo=MagicMock(),
            embedding_model_repo=MagicMock(),
            http_auth_encryption=MagicMock(),
        )
        yield connection, tables, repo
    engine.dispose()


@pytest.mark.parametrize(
    "access, expected",
    [
        ("personal", 200),
        ("viewer", 200),
        ("group_viewer", 200),
        ("organization_child", 200),
        ("distributed", 200),
        ("nonmember", 404),
        ("other_personal_space", 404),
        ("foreign_knowledge", 404),
        ("foreign_space", 404),
        ("foreign_group", 404),
        ("deleted_group", 404),
        ("unrelated_space", 404),
        ("missing_knowledge", 404),
        ("no_import_permission", 200),
        ("empty_history", 200),
    ],
)
async def test_sync_history_obeys_knowledge_read_access(
    integration_access,
    sync_log_database,
    authenticated_integration_app,
    access,
    expected,
):
    case = integration_access
    connection, tables, space_repo = sync_log_database
    knowledge_id, source_space_id, group_id = uuid4(), uuid4(), uuid4()
    visible_space_id = source_space_id
    connection.execute(
        tables[IntegrationKnowledge]
        .insert()
        .values(
            id=knowledge_id,
            space_id=source_space_id,
            tenant_id=uuid4() if access == "foreign_knowledge" else case.user.tenant_id,
        )
    )
    connection.execute(
        tables[Spaces]
        .insert()
        .values(
            id=source_space_id,
            tenant_id=uuid4() if access == "foreign_space" else case.user.tenant_id,
            user_id=(
                case.user.id
                if access == "personal"
                else uuid4()
                if access == "other_personal_space"
                else None
            ),
            tenant_space_id=None
            if access in {"personal", "other_personal_space", "organization_child"}
            else uuid4(),
        )
    )
    if access in {"organization_child", "distributed", "unrelated_space"}:
        visible_space_id = uuid4()
        connection.execute(
            tables[Spaces]
            .insert()
            .values(
                id=visible_space_id,
                tenant_id=case.user.tenant_id,
                user_id=None,
                tenant_space_id=source_space_id
                if access == "organization_child"
                else uuid4(),
            )
        )
        if access == "distributed":
            connection.execute(
                tables[IntegrationKnowledgesSpaces]
                .insert()
                .values(
                    integration_knowledge_id=knowledge_id, space_id=visible_space_id
                )
            )
    if access in {"group_viewer", "foreign_group", "deleted_group"}:
        case.user.user_groups = [UserGroupInDBRead(id=group_id, name="Readers")]
        connection.execute(
            tables[UserGroups]
            .insert()
            .values(
                id=group_id,
                tenant_id=uuid4() if access == "foreign_group" else case.user.tenant_id,
                state="deleted" if access == "deleted_group" else None,
            )
        )
        connection.execute(
            tables[SpacesUserGroups]
            .insert()
            .values(space_id=visible_space_id, user_group_id=group_id, role="viewer")
        )
    elif access not in {"personal", "other_personal_space", "nonmember"}:
        connection.execute(
            tables[SpacesUsers]
            .insert()
            .values(space_id=visible_space_id, user_id=case.user.id, role="viewer")
        )
    if access == "no_import_permission":
        case.user.roles[0].permissions.remove(Permission.INTEGRATIONS)

    logs = [
        SyncLog(
            id=uuid4(),
            integration_knowledge_id=knowledge_id,
            sync_type="delta",
            status="error",
            started_at=datetime(2026, 9, day, tzinfo=timezone.utc),
            error_message="Failed to read /internal/example/file.txt",
        )
        for day in (2, 1)
    ]
    if access == "empty_history":
        logs = []
    sync_log_repo = AsyncMock(spec=SyncLogRepository)
    sync_log_repo.count_by_integration_knowledge.return_value = len(logs)

    async def page(integration_knowledge_id, *, tenant_id, limit, offset):
        assert tenant_id == case.user.tenant_id
        return logs[offset : offset + limit]

    sync_log_repo.get_by_integration_knowledge.side_effect = page
    container = Container(
        user=providers.Object(case.user),
        user_integration_repo=providers.Object(case.integration_repo),
        tenant_integration_repo=providers.Object(AsyncMock()),
        tenant_sharepoint_app_repo=providers.Object(case.app_repo),
        space_repo=providers.Object(space_repo),
        oauth_token_repo=providers.Object(AsyncMock()),
        integration_knowledge_repo=providers.Object(AsyncMock()),
        embedding_model_repo2=providers.Object(AsyncMock()),
        job_service=providers.Object(AsyncMock()),
        sharepoint_subscription_service=providers.Object(AsyncMock()),
        sync_log_repo=providers.Object(sync_log_repo),
    )
    app = authenticated_integration_app(container)
    requested_id = uuid4() if access == "missing_knowledge" else knowledge_id
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/integrations/sync-logs/{requested_id}/",
            params={"skip": 1, "limit": 1},
        )
    assert response.status_code == expected, response.text
    if expected == 200:
        data = response.json()
        assert data["total_count"] == len(logs)
        assert data["offset"] == 1
        assert data["page_size"] == 1
        assert [item["id"] for item in data["items"]] == [
            str(log.id) for log in logs[1:2]
        ]
    else:
        assert "/internal/example" not in response.text
        sync_log_repo.count_by_integration_knowledge.assert_not_awaited()
        sync_log_repo.get_by_integration_knowledge.assert_not_awaited()


@pytest.mark.parametrize(
    "knowledge, permission, expected",
    [
        ("own_tenant", "admin", 200),
        ("own_tenant", "read", 200),
        ("foreign_knowledge", "admin", 404),
        ("foreign_space", "admin", 404),
        ("missing_knowledge", "admin", 404),
    ],
)
async def test_service_key_reads_sync_history_within_its_tenant(
    integration_access,
    sync_log_database,
    authenticated_integration_app,
    knowledge,
    permission,
    expected,
):
    case = integration_access
    connection, tables, space_repo = sync_log_database
    case.user.roles = []
    case.user.active_api_key = MagicMock(
        ownership=ApiKeyOwnership.SERVICE,
        scope_type="tenant",
        scope_id=None,
        permission=permission,
        tenant_id=case.user.tenant_id,
    )
    knowledge_id, space_id = uuid4(), uuid4()
    connection.execute(
        tables[IntegrationKnowledge]
        .insert()
        .values(
            id=knowledge_id,
            space_id=space_id,
            tenant_id=uuid4()
            if knowledge == "foreign_knowledge"
            else case.user.tenant_id,
        )
    )
    connection.execute(
        tables[Spaces]
        .insert()
        .values(
            id=space_id,
            tenant_id=uuid4() if knowledge == "foreign_space" else case.user.tenant_id,
            user_id=None,
            tenant_space_id=uuid4(),
        )
    )
    sync_log_repo = AsyncMock(spec=SyncLogRepository)
    sync_log_repo.count_by_integration_knowledge.return_value = 0
    sync_log_repo.get_by_integration_knowledge.return_value = []
    container = Container(
        user=providers.Object(case.user),
        user_integration_repo=providers.Object(case.integration_repo),
        tenant_integration_repo=providers.Object(AsyncMock()),
        tenant_sharepoint_app_repo=providers.Object(case.app_repo),
        space_repo=providers.Object(space_repo),
        oauth_token_repo=providers.Object(AsyncMock()),
        integration_knowledge_repo=providers.Object(AsyncMock()),
        embedding_model_repo2=providers.Object(AsyncMock()),
        job_service=providers.Object(AsyncMock()),
        sharepoint_subscription_service=providers.Object(AsyncMock()),
        sync_log_repo=providers.Object(sync_log_repo),
    )
    app = authenticated_integration_app(container)
    requested_id = uuid4() if knowledge == "missing_knowledge" else knowledge_id
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/integrations/sync-logs/{requested_id}/")
    assert response.status_code == expected, response.text
    if expected == 200:
        sync_log_repo.count_by_integration_knowledge.assert_awaited_once_with(
            integration_knowledge_id=knowledge_id, tenant_id=case.user.tenant_id
        )
    else:
        sync_log_repo.count_by_integration_knowledge.assert_not_awaited()
        sync_log_repo.get_by_integration_knowledge.assert_not_awaited()
