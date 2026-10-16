"""Admin overview of the tenant's integration knowledge over HTTP, with the
placement query running against SQLite."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from eneo.actors.actors.space_actor import SpaceAccessFacts, SpaceRoleFact
from eneo.ai_models.embedding_models.embedding_model import EmbeddingModelLegacy
from eneo.database.tables.integration_table import (
    IntegrationKnowledge as IntegrationKnowledgeTable,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.integration.domain.entities.integration import Integration
from eneo.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from eneo.integration.domain.entities.tenant_integration import TenantIntegration
from eneo.integration.domain.entities.user_integration import UserIntegration
from eneo.integration.infrastructure.repo_impl.integration_knowledge_repo_impl import (
    IntegrationKnowledgeRepoImpl,
)
from eneo.integration.presentation.admin_integration_router import router
from eneo.main.container.container import Container
from eneo.main.exceptions import ErrorCodes
from eneo.roles.permissions import Permission
from eneo.server.exception_handlers import add_exception_handlers

URL = "/admin/integrations/knowledge/"
EMBEDDING_MODEL = EmbeddingModelLegacy(
    id=uuid4(), name="multilingual-e5-large", is_deprecated=False, open_source=True
)


@pytest.fixture
def placements_database(integration_access):
    # Only the columns the placement query reads; names and types are the real ones.
    metadata = sa.MetaData()
    tables = {}
    for model, names in [
        (
            IntegrationKnowledgeTable,
            ("id", "space_id", "tenant_id", "last_sync_status", "created_at"),
        ),
        (Spaces, ("id", "name", "user_id", "tenant_space_id", "tenant_id")),
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
        repo = IntegrationKnowledgeRepoImpl(
            session=session, mapper=MagicMock(), embedding_model_repo=AsyncMock()
        )
        yield connection, tables, repo
    engine.dispose()


def _app(container: Container) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/admin/integrations")
    add_exception_handlers(app)
    for route in router.routes:
        if isinstance(route, APIRoute):
            for dependency in route.dependant.dependencies:
                if (
                    getattr(dependency.call, "__name__", "")
                    == "_get_container_with_user"
                ):
                    app.dependency_overrides[dependency.call] = lambda: container
    return app


def _member_facts(space_id: UUID, tenant_id: UUID, members: dict) -> SpaceAccessFacts:
    return SpaceAccessFacts(
        id=space_id,
        tenant_id=tenant_id,
        user_id=None,
        tenant_space_id=uuid4(),
        members={
            user_id: SpaceRoleFact(id=user_id, role=role)
            for user_id, role in members.items()
        },
        group_members={},
        default_assistant_id=None,
        assistant_ids=frozenset(),
        app_ids=frozenset(),
    )


async def _get_overview(case, repo, space_repo=None):
    container = Container(
        user=providers.Object(case.user),
        user_integration_repo=providers.Object(case.integration_repo),
        tenant_integration_repo=providers.Object(AsyncMock()),
        tenant_sharepoint_app_repo=providers.Object(case.app_repo),
        space_repo=providers.Object(space_repo or AsyncMock()),
        oauth_token_repo=providers.Object(AsyncMock()),
        integration_knowledge_repo=providers.Object(repo),
        embedding_model_repo2=providers.Object(AsyncMock()),
        job_service=providers.Object(AsyncMock()),
        sharepoint_subscription_service=providers.Object(AsyncMock()),
    )
    async with AsyncClient(
        transport=ASGITransport(app=_app(container)), base_url="http://test"
    ) as client:
        return await client.get(URL)


def _confluence_connection(case) -> UserIntegration:
    return UserIntegration(
        user_id=case.user.id,
        authenticated=True,
        tenant_integration=TenantIntegration(
            tenant_id=case.user.tenant_id,
            integration=Integration(
                name="Confluence", description="", integration_type="confluence"
            ),
        ),
    )


def _insert_space(connection, tables, *, tenant_id, name, user_id=None, parent=None):
    space_id = uuid4()
    connection.execute(
        tables[Spaces]
        .insert()
        .values(
            id=space_id,
            name=name,
            tenant_id=tenant_id,
            user_id=user_id,
            tenant_space_id=parent,
        )
    )
    return space_id


def _insert_knowledge(connection, tables, *, tenant_id, space_id, status, day=1):
    knowledge_id = uuid4()
    connection.execute(
        tables[IntegrationKnowledgeTable]
        .insert()
        .values(
            id=knowledge_id,
            space_id=space_id,
            tenant_id=tenant_id,
            last_sync_status=status,
            created_at=datetime(2026, 10, day, tzinfo=timezone.utc),
        )
    )
    return knowledge_id


async def test_lists_shared_and_organization_items_and_only_counts_personal_ones(
    integration_access, placements_database
):
    case = integration_access
    case.user.roles[0].permissions = [Permission.ADMIN]
    connection, tables, repo = placements_database
    tenant_id = case.user.tenant_id
    organization = _insert_space(
        connection, tables, tenant_id=tenant_id, name="Sundsvalls kommun"
    )
    shared = _insert_space(
        connection, tables, tenant_id=tenant_id, name="Barn", parent=organization
    )
    closed = _insert_space(
        connection, tables, tenant_id=tenant_id, name="Ekonomi", parent=organization
    )
    personal = _insert_space(
        connection, tables, tenant_id=tenant_id, name="Max", user_id=uuid4()
    )
    foreign_tenant = uuid4()
    foreign_shared = _insert_space(
        connection, tables, tenant_id=foreign_tenant, name="Annan", parent=uuid4()
    )
    foreign_personal = _insert_space(
        connection, tables, tenant_id=foreign_tenant, name="Eva", user_id=uuid4()
    )
    org_item = _insert_knowledge(
        connection, tables, tenant_id=tenant_id, space_id=organization, status="success"
    )
    newer_shared_item, older_shared_item = (
        _insert_knowledge(
            connection,
            tables,
            tenant_id=tenant_id,
            space_id=shared,
            status=status,
            day=day,
        )
        for status, day in [("error", 2), ("never", 1)]
    )
    closed_item = _insert_knowledge(
        connection, tables, tenant_id=tenant_id, space_id=closed, status="success"
    )
    for status in ("error", "success", "error"):
        _insert_knowledge(
            connection, tables, tenant_id=tenant_id, space_id=personal, status=status
        )
    # Either side belonging to another tenant keeps a row out, even a mismatched one.
    for item_tenant, space_id in [
        (foreign_tenant, foreign_shared),
        (foreign_tenant, foreign_personal),
        (foreign_tenant, shared),
        (tenant_id, foreign_personal),
    ]:
        _insert_knowledge(
            connection,
            tables,
            tenant_id=item_tenant,
            space_id=space_id,
            status="error",
        )

    knowledge = {
        org_item: IntegrationKnowledge(
            id=org_item,
            name="Styrdokument",
            url="https://contoso.sharepoint.com/sites/KS/Styrdokument",
            tenant_id=tenant_id,
            space_id=organization,
            user_integration=case.integration,
            embedding_model=EMBEDDING_MODEL,
            last_sync_status="success",
            document_count=12,
            folder_path="/Styrdokument",
            wrapper_name="Kommunstyrelsen",
        ),
        newer_shared_item: IntegrationKnowledge(
            id=newer_shared_item,
            name="Rutiner",
            url="https://contoso.atlassian.net/wiki/spaces/BOU",
            tenant_id=tenant_id,
            space_id=shared,
            user_integration=_confluence_connection(case),
            embedding_model=EMBEDDING_MODEL,
            last_sync_status="error",
            last_sync_error="Access denied",
        ),
        older_shared_item: IntegrationKnowledge(
            id=older_shared_item,
            name="Protokoll",
            url="https://contoso.sharepoint.com/sites/BOU/Protokoll",
            tenant_id=tenant_id,
            space_id=shared,
            user_integration=case.integration,
            embedding_model=EMBEDDING_MODEL,
        ),
        closed_item: IntegrationKnowledge(
            id=closed_item,
            name="Budget",
            url="https://contoso.sharepoint.com/sites/EKO/Budget",
            tenant_id=tenant_id,
            space_id=closed,
            user_integration=case.integration,
            embedding_model=EMBEDDING_MODEL,
            last_sync_status="success",
        ),
    }

    async def get_by_ids(ids: list[UUID]) -> list[IntegrationKnowledge]:
        return [knowledge[id] for id in ids]

    repo.get_by_ids = AsyncMock(side_effect=get_by_ids)
    # The admin is a viewer of Barn and not a member of Ekonomi.
    space_repo = AsyncMock()
    space_repo.get_spaces_access_facts.return_value = {
        shared: _member_facts(shared, tenant_id, {case.user.id: "viewer"}),
        closed: _member_facts(closed, tenant_id, {uuid4(): "admin"}),
    }

    response = await _get_overview(case, repo, space_repo)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["personal"] == {"items": 3, "failing": 2}
    assert [
        (
            item["space"],
            item["knowledge"]["id"],
            item["knowledge"]["integration_type"],
            item["knowledge"]["metadata"]["last_sync_status"],
            item["knowledge"]["metadata"]["last_sync_error"],
            item["knowledge"]["metadata"]["document_count"],
        )
        for item in body["items"]
    ] == [
        (
            {
                "id": str(shared),
                "name": "Barn",
                "organization": False,
                "can_open": True,
            },
            str(older_shared_item),
            "sharepoint",
            "never",
            None,
            0,
        ),
        (
            {
                "id": str(shared),
                "name": "Barn",
                "organization": False,
                "can_open": True,
            },
            str(newer_shared_item),
            "confluence",
            "error",
            "Access denied",
            0,
        ),
        (
            {
                "id": str(closed),
                "name": "Ekonomi",
                "organization": False,
                "can_open": False,
            },
            str(closed_item),
            "sharepoint",
            "success",
            None,
            0,
        ),
        (
            {
                "id": str(organization),
                "name": "Sundsvalls kommun",
                "organization": True,
                # Opening it makes every tenant admin its admin.
                "can_open": True,
            },
            str(org_item),
            "sharepoint",
            "success",
            None,
            12,
        ),
    ]
    org_knowledge = body["items"][3]["knowledge"]
    assert org_knowledge["folder_path"] == "/Styrdokument"
    assert org_knowledge["wrapper_name"] == "Kommunstyrelsen"
    repo.get_by_ids.assert_awaited_once_with(
        [older_shared_item, newer_shared_item, closed_item, org_item]
    )
    # The shared spaces' facts are read at once; the organization space needs none.
    space_repo.get_spaces_access_facts.assert_awaited_once()
    (asked,) = space_repo.get_spaces_access_facts.await_args.args
    assert sorted(asked) == sorted([shared, closed])


@pytest.mark.parametrize(
    "permissions", [[], [Permission.INTEGRATIONS, Permission.ASSISTANTS]]
)
async def test_non_admins_are_refused_before_anything_is_read(
    integration_access, placements_database, permissions
):
    case = integration_access
    case.user.roles[0].permissions = permissions
    _, _, repo = placements_database
    repo.get_by_ids = AsyncMock()
    space_repo = AsyncMock()

    response = await _get_overview(case, repo, space_repo)

    assert response.status_code == 403
    assert response.json()["eneo_error_code"] == ErrorCodes.UNAUTHORIZED.value
    repo.session.execute.assert_not_awaited()
    repo.get_by_ids.assert_not_awaited()
    space_repo.get_spaces_access_facts.assert_not_awaited()
