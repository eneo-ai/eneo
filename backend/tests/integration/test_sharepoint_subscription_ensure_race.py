"""Concurrent callers for one site create or recreate its subscription once."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.integration_table import (
    Integration as IntegrationDB,
)
from eneo.database.tables.integration_table import (
    TenantIntegration as TenantIntegrationDB,
)
from eneo.database.tables.integration_table import (
    UserIntegration as UserIntegrationDB,
)
from eneo.database.tables.sharepoint_subscription_table import (
    SharePointSubscription as SubscriptionDB,
)
from eneo.integration.infrastructure.sharepoint_subscription_service import (
    SharePointSubscriptionService,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("sharepoint_webhook_configured"),
]

SITE = "contoso.sharepoint.com,site,web"


async def _connection(db_container) -> UUID:
    async with db_container() as container:
        session = container.session()
        user = container.user()
        integration = IntegrationDB(
            name=f"ensure-race-{uuid4()}",
            description="ensure race",
            integration_type="sharepoint",
        )
        session.add(integration)
        await session.flush()
        tenant_integration = TenantIntegrationDB(
            tenant_id=user.tenant_id, integration_id=integration.id
        )
        session.add(tenant_integration)
        await session.flush()
        connection = UserIntegrationDB(
            user_id=user.id,
            tenant_id=user.tenant_id,
            tenant_integration_id=tenant_integration.id,
            authenticated=True,
        )
        session.add(connection)
        await session.flush()
        return connection.id


async def _race(db_container, connection_id: UUID) -> tuple[list[str], list[str]]:
    created: list[str] = []

    async def create_at_graph(**_kwargs) -> str:
        # Wide enough that both callers would pass the read without the lock.
        await asyncio.sleep(0.3)
        created.append(f"graph-{len(created)}")
        return created[-1]

    async def ensure() -> str:
        async with db_container() as container:
            service = container.sharepoint_subscription_service()
            subscription = await service.ensure_subscription_for_site(
                user_integration_id=connection_id,
                site_id=SITE,
                token=MagicMock(access_token="token", base_url="https://graph"),
            )
            assert subscription is not None
            return subscription.subscription_id

    with (
        patch.object(
            SharePointSubscriptionService,
            "_create_graph_subscription",
            side_effect=create_at_graph,
        ),
        patch.object(
            SharePointSubscriptionService,
            "_resolve_drive_id",
            return_value="drive-1",
        ),
        patch.object(
            SharePointSubscriptionService,
            "_delete_graph_subscription",
            return_value=True,
        ),
    ):
        used = await asyncio.wait_for(asyncio.gather(ensure(), ensure()), timeout=30)
    return created, list(used)


async def test_two_imports_on_a_new_site_create_one_graph_subscription(db_container):
    connection_id = await _connection(db_container)

    created, used = await _race(db_container, connection_id)

    assert created == ["graph-0"]
    assert used == ["graph-0", "graph-0"]


async def test_two_syncs_on_an_expired_subscription_recreate_it_once(db_container):
    connection_id = await _connection(db_container)
    async with db_container() as container:
        container.session().add(
            SubscriptionDB(
                user_integration_id=connection_id,
                site_id=SITE,
                subscription_id="graph-expired",
                drive_id="drive-1",
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        )

    created, used = await _race(db_container, connection_id)

    assert created == ["graph-0"]
    assert used == ["graph-0", "graph-0"]
    async with db_container() as container:
        stored = (
            await container.session().scalars(
                sa.select(SubscriptionDB.subscription_id).where(
                    SubscriptionDB.user_integration_id == connection_id
                )
            )
        ).all()
    assert stored == ["graph-0"]
