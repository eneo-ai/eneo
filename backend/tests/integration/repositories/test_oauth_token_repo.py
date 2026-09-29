"""OAuth token persistence must load the integration graph without implicit I/O."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from uuid import uuid4

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.integration_table import (
    Integration as IntegrationDB,
)
from eneo.database.tables.integration_table import (
    TenantIntegration as TenantIntegrationDB,
)
from eneo.database.tables.integration_table import (
    UserIntegration as UserIntegrationDB,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.integration.domain.entities.integration import Integration
from eneo.integration.domain.entities.oauth_token import OauthToken
from eneo.integration.domain.entities.tenant_integration import TenantIntegration
from eneo.integration.domain.entities.user_integration import UserIntegration
from eneo.integration.domain.value_objects import IntegrationType
from eneo.integration.infrastructure.mappers.oauth_token_mapper import OauthTokenMapper
from eneo.integration.infrastructure.repo_impl.oauth_token_repo_impl import (
    OauthTokenRepoImpl,
)
from eneo.settings.encryption_service import EncryptionService


@pytest.mark.integration
@pytest.mark.parametrize(
    "integration_type", [IntegrationType.Sharepoint, IntegrationType.Confluence]
)
async def test_token_round_trip_loads_complete_integration(
    db_session: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    integration_type: IntegrationType,
) -> None:
    tenant_id, user_id, integration_id = uuid4(), uuid4(), uuid4()
    tenant_integration_id, user_integration_id = uuid4(), uuid4()
    integration_name = f"oauth-regression-{integration_id}"
    user_integration = UserIntegration(
        id=user_integration_id,
        user_id=user_id,
        authenticated=True,
        tenant_integration=TenantIntegration(
            id=tenant_integration_id,
            tenant_id=tenant_id,
            integration=Integration(
                id=integration_id,
                name=integration_name,
                description="OAuth repository regression",
                integration_type=integration_type.value,
            ),
        ),
    )
    token = OauthToken(
        access_token="test-access-token",
        refresh_token="test-refresh-token",
        token_type=integration_type,
        user_integration=user_integration,
    )
    mapper = OauthTokenMapper(EncryptionService(Fernet.generate_key().decode()))

    async with db_session() as session:
        # Core inserts leave the ORM identity map empty. Previously loaded
        # Integration objects must not mask a missing relationship loader.
        await session.execute(
            sa.insert(Tenants).values(
                id=tenant_id, name=f"oauth-{tenant_id}", quota_limit=1000
            )
        )
        await session.execute(
            sa.insert(Users).values(
                id=user_id,
                tenant_id=tenant_id,
                email=f"oauth-{user_id}@example.com",
                state="active",
            )
        )
        await session.execute(
            sa.insert(IntegrationDB).values(
                id=integration_id,
                name=integration_name,
                description="OAuth repository regression",
                integration_type=integration_type.value,
            )
        )
        await session.execute(
            sa.insert(TenantIntegrationDB).values(
                id=tenant_integration_id,
                tenant_id=tenant_id,
                integration_id=integration_id,
            )
        )
        await session.execute(
            sa.insert(UserIntegrationDB).values(
                id=user_integration_id,
                tenant_id=tenant_id,
                user_id=user_id,
                tenant_integration_id=tenant_integration_id,
                authenticated=True,
            )
        )

        repo = OauthTokenRepoImpl(session, mapper)
        saved = await repo.add(token)
        session.expunge_all()
        loaded = await repo.one(id=saved.id)
        assert loaded.access_token == "test-access-token"
        session.expunge_all()
        loaded.access_token = "refreshed-access-token"
        updated = await repo.update(loaded)

    # Returned domain objects remain usable after the database session closes.
    for result in (saved, loaded, updated):
        assert result.id == saved.id
        assert result.token_type == integration_type
        assert result.refresh_token == "test-refresh-token"
        assert result.user_integration.id == user_integration_id
        assert result.user_integration.user_id == user_id
        assert result.user_integration.authenticated is True
        tenant_integration = result.user_integration.tenant_integration
        assert tenant_integration.id == tenant_integration_id
        assert tenant_integration.tenant_id == tenant_id
        assert tenant_integration.integration.id == integration_id
        assert tenant_integration.integration.name == integration_name
        assert tenant_integration.integration_type == integration_type.value
    assert saved.access_token == "test-access-token"
    assert updated.access_token == "refreshed-access-token"
