from typing import TYPE_CHECKING, Optional

from intric.integration.domain.entities.user_integration import (
    UserIntegration,
)
from intric.main.exceptions import UnauthorizedException
from intric.main.logging import get_logger
from intric.roles.permissions import Permission

logger = get_logger(__name__)

if TYPE_CHECKING:
    from uuid import UUID

    from intric.integration.domain.repositories.tenant_integration_repo import (
        TenantIntegrationRepository,
    )
    from intric.integration.domain.repositories.user_integration_repo import (
        UserIntegrationRepository,
    )
    from intric.integration.domain.repositories.tenant_sharepoint_app_repo import (
        TenantSharePointAppRepository,
    )
    from intric.spaces.space import Space
    from intric.users.user import UserInDB


class UserIntegrationService:
    def __init__(
        self,
        user_integration_repo: "UserIntegrationRepository",
        tenant_integration_repo: "TenantIntegrationRepository",
        user: "UserInDB",
        tenant_sharepoint_app_repo: Optional["TenantSharePointAppRepository"] = None,
    ):
        self.user_integration_repo = user_integration_repo
        self.tenant_integration_repo = tenant_integration_repo
        self.user = user
        self.tenant_sharepoint_app_repo = tenant_sharepoint_app_repo

    async def get_my_integrations(
        self,
        user_id: "UUID",
        tenant_id: "UUID",
    ) -> list["UserIntegration"]:
        user_oauth_list = await self.user_integration_repo.query(user_id=user_id)

        import sqlalchemy as sa
        from sqlalchemy.orm import selectinload
        from intric.database.tables.integration_table import (
            UserIntegration as UserIntegrationDB,
            TenantIntegration as TenantIntegrationDB,
        )
        from intric.integration.domain.factories.user_integration_factory import (
            UserIntegrationFactory,
        )

        tenant_app_stmt = (
            sa.select(UserIntegrationDB)
            .options(
                selectinload(UserIntegrationDB.tenant_integration).selectinload(
                    TenantIntegrationDB.integration
                )
            )
            .where(
                sa.and_(
                    UserIntegrationDB.user_id.is_(None),  # Person-independent
                    UserIntegrationDB.auth_type == "tenant_app",
                    UserIntegrationDB.tenant_integration.has(tenant_id=tenant_id)
                )
            )
        )
        tenant_app_result = await self.user_integration_repo.session.execute(tenant_app_stmt)
        tenant_app_db_models = [row[0] for row in tenant_app_result.all()]
        tenant_app_list = UserIntegrationFactory.create_entities(records=tenant_app_db_models)

        user_oauth_map = {
            item.tenant_integration.id: item for item in user_oauth_list
        }
        tenant_app_map = {
            item.tenant_integration.id: item for item in tenant_app_list
        }

        available = await self.tenant_integration_repo.query(tenant_id=tenant_id)

        results = []
        for a in available:
            if a.id in tenant_app_map:
                results.append(tenant_app_map[a.id])

            if a.id in user_oauth_map:
                results.append(user_oauth_map[a.id])
            else:
                user_integration = UserIntegration(
                    tenant_integration=a,
                    user_id=user_id
                )
                results.append(user_integration)

        return results

    async def disconnect_integration(self, user_integration_id: "UUID") -> None:
        integration = await self.user_integration_repo.one(id=user_integration_id)

        if integration.auth_type == "user_oauth":
            if integration.user_id != self.user.id:
                raise UnauthorizedException(
                    "You can only disconnect your own integrations"
                )
        elif integration.auth_type == "tenant_app":
            raise UnauthorizedException(
                "Tenant app integrations cannot be disconnected here. "
                "Please use the admin panel to deactivate the SharePoint app."
            )

        await self.user_integration_repo.remove(id=integration.id)

    async def get_available_integrations_for_space(
        self,
        space: "Space",
    ) -> list["UserIntegration"]:
        """Get available integrations filtered by space type and tenant configuration.

        - Personal spaces: Only user_oauth integrations IF tenant has SharePoint app configured
        - Shared/Organization spaces: Only authenticated tenant_app integrations (admin-only)
        """
        all_integrations = await self.get_my_integrations(
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
        )

        tenant_app = None
        if self.tenant_sharepoint_app_repo:
            try:
                tenant_app = await self.tenant_sharepoint_app_repo.one_or_none(
                    tenant_id=self.user.tenant_id
                )
            except Exception as e:
                logger.warning(
                    f"Failed to fetch tenant SharePoint app: {type(e).__name__}: {str(e)}",
                    extra={"tenant_id": str(self.user.tenant_id)}
                )

        is_admin = Permission.ADMIN in self.user.permissions

        if space.is_personal():
            available = []
            for integration in all_integrations:
                if integration.auth_type != "user_oauth" and integration.authenticated:
                    continue

                if integration.tenant_integration.integration.integration_type == "sharepoint":
                    if not tenant_app or not tenant_app.is_active:
                        continue

                available.append(integration)

            return available
        else:
            # SECURITY: tenant_app integrations (Sites.Read.All) are admin-only
            if not is_admin:
                return []

            return [
                integration for integration in all_integrations
                if integration.authenticated and integration.auth_type == "tenant_app"
            ]
