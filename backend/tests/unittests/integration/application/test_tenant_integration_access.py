"""Tenant administration contracts using real services, repositories and SQLite."""

import sqlite3
from dataclasses import dataclass
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from eneo.audit.domain.action_types import ActionType
from eneo.database.tables.integration_table import (
    Integration,
    IntegrationKnowledge,
    OauthToken,
    TenantIntegration,
    UserIntegration,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.integration.application.tenant_integration_service import (
    TenantIntegrationService,
)
from eneo.integration.infrastructure.mappers.integration_mapper import IntegrationMapper
from eneo.integration.infrastructure.mappers.tenant_integration_mapper import (
    TenantIntegrationMapper,
)
from eneo.integration.infrastructure.repo_impl.integration_repo_impl import (
    IntegrationRepoImpl,
)
from eneo.integration.infrastructure.repo_impl.tenant_integration_repo_impl import (
    TenantIntegrationRepoImpl,
)
from eneo.main.container.container import Container
from eneo.main.exceptions import UnauthorizedException
from eneo.roles.permissions import Permission


@dataclass
class TenantAdministration:
    app: FastAPI
    service: TenantIntegrationService
    database: Session
    tables: sa.MetaData
    available_id: UUID
    foreign_id: UUID
    owned_ids: dict[str, set[UUID]]
    audit: AsyncMock

    def stored_ids(self) -> dict[str, set[UUID]]:
        return {
            name: set(self.database.scalars(sa.select(table.c.id)))
            for name, table in self.tables.tables.items()
        }


@pytest.fixture(params=["sharepoint", "confluence"])
def tenant_administration(request, integration_access, authenticated_integration_app):
    case = integration_access
    catalog = case.integration.tenant_integration.integration
    metadata = sa.MetaData()
    tenants = sa.Table(
        Tenants.__tablename__, metadata, sa.Column("id", sa.Uuid, primary_key=True)
    )
    Integration.__table__.to_metadata(metadata)
    TenantIntegration.__table__.to_metadata(metadata)
    # Copy the real cascade definitions, omitting unrelated PostgreSQL payloads
    # and foreign keys. Repository queries use the full production parent tables.
    for model, parent_name in [
        (UserIntegration, "tenant_integration_id"),
        (OauthToken, "user_integration_id"),
        (IntegrationKnowledge, "user_integration_id"),
    ]:
        parent = model.__table__.c[parent_name]
        (foreign_key,) = parent.foreign_keys
        sa.Table(
            model.__tablename__,
            metadata,
            sa.Column("id", model.__table__.c.id.type, primary_key=True),
            sa.Column(
                parent_name,
                parent.type,
                sa.ForeignKey(
                    foreign_key.target_fullname, ondelete=foreign_key.ondelete
                ),
                nullable=False,
            ),
        )

    engine = sa.create_engine("sqlite://")
    try:
        with engine.connect() as connection:
            sqlite = connection.connection.driver_connection
            assert isinstance(sqlite, sqlite3.Connection)
            sqlite.create_function("gen_random_uuid", 0, lambda: uuid4().hex)
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            metadata.create_all(connection)
            with Session(connection) as database:
                available_id, foreign_id, foreign_tenant = uuid4(), uuid4(), uuid4()
                database.execute(
                    tenants.insert(),
                    [{"id": case.user.tenant_id}, {"id": foreign_tenant}],
                )
                database.execute(
                    sa.insert(Integration),
                    [
                        {
                            "id": id,
                            "name": name,
                            "description": "",
                            "integration_type": request.param,
                        }
                        for id, name in [
                            (catalog.id, "Enabled"),
                            (available_id, "Available"),
                        ]
                    ],
                )
                owned_ids: dict[str, set[UUID]] = {}
                for tenant_id, integration_id in [
                    (case.user.tenant_id, case.integration.tenant_integration.id),
                    (foreign_tenant, foreign_id),
                ]:
                    database.execute(
                        sa.insert(TenantIntegration).values(
                            id=integration_id,
                            tenant_id=tenant_id,
                            integration_id=catalog.id,
                        )
                    )
                    if tenant_id == case.user.tenant_id:
                        owned_ids[TenantIntegration.__tablename__] = {integration_id}
                    for _ in range(2):
                        user_integration_id = uuid4()
                        for model, parent_name, id, parent_id in [
                            (
                                UserIntegration,
                                "tenant_integration_id",
                                user_integration_id,
                                integration_id,
                            ),
                            (
                                OauthToken,
                                "user_integration_id",
                                uuid4(),
                                user_integration_id,
                            ),
                            (
                                IntegrationKnowledge,
                                "user_integration_id",
                                uuid4(),
                                user_integration_id,
                            ),
                        ]:
                            table = metadata.tables[model.__tablename__]
                            database.execute(
                                table.insert().values(id=id, **{parent_name: parent_id})
                            )
                            if tenant_id == case.user.tenant_id:
                                owned_ids.setdefault(table.name, set()).add(id)

                # Adapt only async I/O; execute production SQL, mappers and policy.
                session = AsyncMock(spec=AsyncSession)
                session.scalar.side_effect = database.scalar
                session.scalars.side_effect = database.scalars
                session.execute.side_effect = database.execute
                audit = AsyncMock()
                container = Container(
                    user=providers.Object(case.user),
                    integration_repo=providers.Object(
                        IntegrationRepoImpl(session, IntegrationMapper())
                    ),
                    tenant_integration_repo=providers.Object(
                        TenantIntegrationRepoImpl(session, TenantIntegrationMapper())
                    ),
                    audit_service=providers.Object(audit),
                )
                yield TenantAdministration(
                    app=authenticated_integration_app(container),
                    service=container.tenant_integration_service(),
                    database=database,
                    tables=metadata,
                    available_id=available_id,
                    foreign_id=foreign_id,
                    owned_ids=owned_ids,
                    audit=audit,
                )
    finally:
        engine.dispose()


@pytest.mark.parametrize("permissions", [[], [Permission.INTEGRATIONS]])
@pytest.mark.parametrize("operation", ["add", "remove"])
@pytest.mark.parametrize("known_id", [True, False])
async def test_non_admin_requests_preserve_all_rows(
    integration_access, tenant_administration, permissions, operation, known_id
):
    case = tenant_administration
    integration_access.user.roles[0].permissions = permissions.copy()
    id = (
        case.available_id
        if operation == "add"
        else integration_access.integration.tenant_integration.id
    )
    if not known_id:
        id = uuid4()
    before = case.stored_ids()

    async with AsyncClient(
        transport=ASGITransport(app=case.app), base_url="http://test"
    ) as client:
        response = await client.request(
            "POST" if operation == "add" else "DELETE",
            f"/integrations/tenant/{operation}/{id}/",
        )

    assert response.status_code == 403
    assert case.stored_ids() == before
    case.audit.log_async.assert_not_awaited()


@pytest.mark.parametrize("operation", ["add", "remove"])
async def test_service_itself_requires_admin(
    integration_access, tenant_administration, operation
):
    case = tenant_administration
    before = case.stored_ids()
    with pytest.raises(UnauthorizedException):
        if operation == "add":
            await case.service.create_tenant_integration(case.available_id)
        else:
            await case.service.remove_tenant_integration(
                integration_access.integration.tenant_integration.id
            )
    assert case.stored_ids() == before


async def test_admin_can_enable_integration_for_own_tenant(
    integration_access, tenant_administration
):
    case = tenant_administration
    integration_access.user.roles[0].permissions = [Permission.ADMIN]
    before = case.stored_ids()
    async with AsyncClient(
        transport=ASGITransport(app=case.app), base_url="http://test"
    ) as client:
        response = await client.post(f"/integrations/tenant/add/{case.available_id}/")

    assert response.status_code == 200
    assert response.json()["integration_id"] == str(case.available_id)
    id = UUID(response.json()["id"])
    record = case.database.get(TenantIntegration, id)
    assert record is not None
    assert record.tenant_id == integration_access.user.tenant_id
    before[TenantIntegration.__tablename__].add(id)
    assert case.stored_ids() == before
    assert (
        case.audit.log_async.await_args.kwargs["action"] == ActionType.INTEGRATION_ADDED
    )


async def test_admin_removal_only_cascades_in_own_tenant(
    integration_access, tenant_administration
):
    case = tenant_administration
    integration_access.user.roles[0].permissions = [Permission.ADMIN]
    id = integration_access.integration.tenant_integration.id
    before = case.stored_ids()
    async with AsyncClient(
        transport=ASGITransport(app=case.app), base_url="http://test"
    ) as client:
        response = await client.delete(f"/integrations/tenant/remove/{id}/")

    assert response.status_code == 204
    assert case.stored_ids() == {
        name: ids - case.owned_ids.get(name, set()) for name, ids in before.items()
    }
    assert case.foreign_id in case.stored_ids()[TenantIntegration.__tablename__]
    assert (
        case.audit.log_async.await_args.kwargs["action"]
        == ActionType.INTEGRATION_REMOVED
    )
    assert case.audit.log_async.await_args.kwargs["entity_id"] == id


@pytest.mark.parametrize("target", ["foreign", "unknown"])
async def test_admin_cannot_remove_other_tenants_or_unknown_ids(
    integration_access, tenant_administration, target
):
    case = tenant_administration
    integration_access.user.roles[0].permissions = [Permission.ADMIN]
    id = case.foreign_id if target == "foreign" else uuid4()
    before = case.stored_ids()
    async with AsyncClient(
        transport=ASGITransport(app=case.app), base_url="http://test"
    ) as client:
        response = await client.delete(f"/integrations/tenant/remove/{id}/")

    assert response.status_code == 404
    assert case.stored_ids() == before
    case.audit.log_async.assert_not_awaited()


@pytest.mark.parametrize("target, expected", [("duplicate", 400), ("unknown", 404)])
async def test_admin_cannot_add_duplicate_or_unknown_integration(
    integration_access, tenant_administration, target, expected
):
    case = tenant_administration
    integration_access.user.roles[0].permissions = [Permission.ADMIN]
    id = (
        integration_access.integration.tenant_integration.integration.id
        if target == "duplicate"
        else uuid4()
    )
    before = case.stored_ids()
    async with AsyncClient(
        transport=ASGITransport(app=case.app), base_url="http://test"
    ) as client:
        response = await client.post(f"/integrations/tenant/add/{id}/")

    assert response.status_code == expected
    assert case.stored_ids() == before
    case.audit.log_async.assert_not_awaited()


async def test_non_admin_can_still_list_own_tenant_integrations(
    integration_access, tenant_administration
):
    case = tenant_administration
    async with AsyncClient(
        transport=ASGITransport(app=case.app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/integrations/tenant/", params={"filter": "tenant_only"}
        )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [
        str(integration_access.integration.tenant_integration.id)
    ]
