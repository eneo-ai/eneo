"""Real users, connections and space policy for integration access tests."""

from collections.abc import Callable
from dataclasses import dataclass
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from eneo.actors import ActorFactory, ActorManager
from eneo.integration.application.user_integration_service import UserIntegrationService
from eneo.integration.domain.entities.integration import Integration
from eneo.integration.domain.entities.tenant_integration import TenantIntegration
from eneo.integration.domain.entities.tenant_sharepoint_app import TenantSharePointApp
from eneo.integration.domain.entities.user_integration import UserIntegration
from eneo.integration.domain.repositories.tenant_integration_repo import (
    TenantIntegrationRepository,
)
from eneo.integration.domain.repositories.tenant_sharepoint_app_repo import (
    TenantSharePointAppRepository,
)
from eneo.integration.domain.repositories.user_integration_repo import (
    UserIntegrationRepository,
)
from eneo.integration.presentation.integration_auth_router import router as auth_router
from eneo.integration.presentation.integration_router import router
from eneo.main.container.container import Container
from eneo.main.exceptions import NotFoundException
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleInDB
from eneo.server.exception_handlers import add_exception_handlers
from eneo.spaces.api.space_models import SpaceMember, SpaceRoleValue
from eneo.spaces.space import Space
from eneo.users.user import UserInDB


@pytest.fixture
def authenticated_integration_app() -> Callable[[Container], FastAPI]:
    def create_app(container: Container) -> FastAPI:
        app = FastAPI()
        app.include_router(auth_router, prefix="/integrations/auth")
        app.include_router(router, prefix="/integrations")
        add_exception_handlers(app)
        for route in (*auth_router.routes, *router.routes):
            if isinstance(route, APIRoute):
                for dependency in route.dependant.dependencies:
                    if (
                        getattr(dependency.call, "__name__", "")
                        == "_get_container_with_user"
                    ):
                        app.dependency_overrides[dependency.call] = lambda: container
        return app

    return create_app


@dataclass
class IntegrationAccessCase:
    user: UserInDB
    integration: UserIntegration
    space: Space
    app: TenantSharePointApp
    service: UserIntegrationService
    integration_repo: AsyncMock
    app_repo: AsyncMock

    def use_organization_connection(self) -> None:
        self.user.roles[0].permissions.append(Permission.ADMIN)
        self.integration.auth_type = "tenant_app"
        self.integration.user_id = None
        self.integration.tenant_app_id = self.app.id
        self.space.user_id = None
        self.space.tenant_space_id = uuid4()
        self.space.members[self.user.id] = SpaceMember(
            id=self.user.id, email=self.user.email, role=SpaceRoleValue.ADMIN
        )


@pytest.fixture
def integration_access(user: UserInDB) -> IntegrationAccessCase:
    user = user.model_copy(deep=True)
    user.roles = [
        RoleInDB(
            id=uuid4(),
            name="Importer",
            tenant_id=user.tenant_id,
            permissions=[Permission.INTEGRATIONS],
        )
    ]
    integration = UserIntegration(
        user_id=user.id,
        authenticated=True,
        tenant_integration=TenantIntegration(
            tenant_id=user.tenant_id,
            integration=Integration(
                name="SharePoint", description="", integration_type="sharepoint"
            ),
        ),
    )
    app = TenantSharePointApp(
        tenant_id=user.tenant_id,
        client_id="test-app",
        client_secret="test-secret",
        tenant_domain="example.com",
    )
    space = Space(
        id=uuid4(),
        tenant_id=user.tenant_id,
        tenant_space_id=None,
        user_id=user.id,
        name="Personal",
        description=None,
        embedding_models=[],
        completion_models=[],
        transcription_models=[],
        mcp_servers=[],
        default_assistant=None,
        assistants=[],
        apps=[],
        services=[],
        websites=[],
        collections=[],
        integration_knowledge_list=[],
        members={},
    )
    integration_repo = AsyncMock(spec=UserIntegrationRepository)
    app_repo = AsyncMock(spec=TenantSharePointAppRepository)

    async def find_integration(
        id: UUID | None = None, *, tenant_id: UUID | None = None
    ):
        if id != integration.id or (
            tenant_id is not None
            and tenant_id != integration.tenant_integration.tenant_id
        ):
            raise NotFoundException("Integration not found")
        return integration

    async def find_app(id: UUID | None = None, *, tenant_id: UUID | None = None):
        if id != app.id or (tenant_id is not None and tenant_id != app.tenant_id):
            raise NotFoundException("Integration not found")
        return app

    integration_repo.one.side_effect = find_integration
    app_repo.one.side_effect = find_app
    service = UserIntegrationService(
        user_integration_repo=integration_repo,
        tenant_integration_repo=AsyncMock(spec=TenantIntegrationRepository),
        user=user,
        actor_manager=ActorManager(user=user, factory=ActorFactory()),
        tenant_sharepoint_app_repo=app_repo,
    )
    return IntegrationAccessCase(
        user, integration, space, app, service, integration_repo, app_repo
    )
