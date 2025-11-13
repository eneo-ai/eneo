from typing import TYPE_CHECKING
from uuid import UUID

from intric.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from intric.integration.presentation.models import (
    ConfluenceContentTaskParam,
    SharepointContentTaskParam,
)
from intric.jobs.job_models import JobInDb, Task
from intric.main.exceptions import BadRequestException, UnauthorizedException
from intric.main.logging import get_logger
from intric.roles.permissions import Permission

if TYPE_CHECKING:
    from intric.actors import ActorManager
    from intric.embedding_models.domain.embedding_model_repo import EmbeddingModelRepository
    from intric.integration.domain.repositories.integration_knowledge_repo import (
        IntegrationKnowledgeRepository,
    )
    from intric.integration.domain.repositories.oauth_token_repo import (
        OauthTokenRepository,
    )
    from intric.integration.domain.repositories.user_integration_repo import (
        UserIntegrationRepository,
    )
    from intric.integration.domain.repositories.tenant_sharepoint_app_repo import (
        TenantSharePointAppRepository,
    )
    from intric.integration.infrastructure.auth_service.tenant_app_auth_service import (
        TenantAppAuthService,
    )
    from intric.jobs.job_service import JobService
    from intric.spaces.space import Space
    from intric.integration.infrastructure.sharepoint_subscription_service import SharePointSubscriptionService
    from intric.spaces.space_repo import SpaceRepository
    from intric.users.user import UserInDB


logger = get_logger(__name__)


class SimpleToken:
    """Simple token wrapper for subscription service compatibility.

    Used for tenant_app integrations where we don't have an OauthToken
    in the database, but need a token object with access_token attribute.
    """
    def __init__(self, access_token: str):
        self.access_token = access_token


class IntegrationKnowledgeService:
    def __init__(
        self,
        job_service: "JobService",
        user: "UserInDB",
        oauth_token_repo: "OauthTokenRepository",
        space_repo: "SpaceRepository",
        integration_knowledge_repo: "IntegrationKnowledgeRepository",
        embedding_model_repo: "EmbeddingModelRepository",
        user_integration_repo: "UserIntegrationRepository",
        actor_manager: "ActorManager",
        sharepoint_subscription_service: "SharePointSubscriptionService",
        tenant_sharepoint_app_repo: "TenantSharePointAppRepository",
        tenant_app_auth_service: "TenantAppAuthService",
    ):
        self.job_service = job_service
        self.user = user
        self.oauth_token_repo = oauth_token_repo
        self.space_repo = space_repo
        self.integration_knowledge_repo = integration_knowledge_repo
        self.embedding_model_repo = embedding_model_repo
        self.user_integration_repo = user_integration_repo
        self.actor_manager = actor_manager
        self.sharepoint_subscription_service = sharepoint_subscription_service
        self.tenant_sharepoint_app_repo = tenant_sharepoint_app_repo
        self.tenant_app_auth_service = tenant_app_auth_service

    async def create_space_integration_knowledge(
        self,
        user_integration_id: UUID,
        name: str,
        embedding_model_id: UUID,
        space_id: UUID,
        key: str,
        url: str,
        folder_id: str = None,
        folder_path: str = None,
        selected_item_type: str = None,
    ) -> tuple[IntegrationKnowledge, "JobInDb"]:
        space = await self.space_repo.one(id=space_id)
        if not space.is_embedding_model_in_space(embedding_model_id=embedding_model_id):
            raise BadRequestException("No valid embedding model")

        user_integration = await self.user_integration_repo.one(id=user_integration_id)

        # SECURITY: tenant_app integrations (Sites.Read.All) require admin permission
        if user_integration.auth_type == "tenant_app":
            if Permission.ADMIN not in self.user.permissions:
                raise UnauthorizedException(
                    "Admin permission is required to import from organization-wide SharePoint integrations. "
                    "Please contact your administrator."
                )

        embedding_model = await self.embedding_model_repo.one(model_id=embedding_model_id)
        site_id_value = key if user_integration.integration_type == "sharepoint" else None
        obj = IntegrationKnowledge(
            name=name,
            space_id=space_id,
            embedding_model=embedding_model,
            user_integration=user_integration,
            tenant_id=self.user.tenant_id,
            url=url,
            site_id=site_id_value,
            folder_id=folder_id,
            folder_path=folder_path,
            selected_item_type=selected_item_type,
        )
        knowledge = await self.integration_knowledge_repo.add(obj=obj)

        await self._distribute_knowledge_if_org_space(knowledge, space)

        if user_integration.auth_type == "tenant_app":
            if not user_integration.tenant_app_id:
                raise BadRequestException("Tenant app ID is required for tenant_app integrations")

            tenant_app = await self.tenant_sharepoint_app_repo.one(id=user_integration.tenant_app_id)
            access_token = await self.tenant_app_auth_service.get_access_token(tenant_app)
            token = SimpleToken(access_token=access_token)
            token_id = None
            tenant_app_id = tenant_app.id
        else:
            oauth_token = await self.oauth_token_repo.one(user_integration_id=user_integration_id)
            token = oauth_token
            token_id = oauth_token.id
            tenant_app_id = None

        if hasattr(token, 'token_type') and token.token_type.is_confluence:
            job = await self.job_service.queue_job(
                task=Task.PULL_CONFLUENCE_CONTENT,
                name=name,
                task_params=ConfluenceContentTaskParam(
                    user_id=self.user.id,
                    id=user_integration_id,
                    token_id=token_id,
                    space_key=key,
                    integration_knowledge_id=knowledge.id,
                ),
            )
        elif user_integration.integration_type == "sharepoint":
            job = await self.job_service.queue_job(
                task=Task.PULL_SHAREPOINT_CONTENT,
                name=name,
                task_params=SharepointContentTaskParam(
                    user_id=self.user.id,
                    id=user_integration_id,
                    token_id=token_id,
                    tenant_app_id=tenant_app_id,
                    integration_knowledge_id=knowledge.id,
                    site_id=key,
                    folder_id=folder_id,
                    folder_path=folder_path,
                ),
            )
            # Register site-level webhook subscription (shared across all integrations on this site)
            # One subscription per (user_integration, site) handles all folders/files on that site
            # Webhook filtering happens in the webhook handler based on folder_id in IntegrationKnowledge
            logger.info("Ensuring site-level subscription for knowledge %s (site=%s)", knowledge.id, key[:30])
            try:
                subscription = await self.sharepoint_subscription_service.ensure_subscription_for_site(
                    user_integration_id=user_integration_id,
                    site_id=key,
                    token=token
                )
                if subscription:
                    # Link this knowledge to the shared subscription
                    knowledge.sharepoint_subscription_id = subscription.id
                    knowledge = await self.integration_knowledge_repo.update(knowledge)
                    logger.info(
                        "Successfully linked knowledge %s to subscription %s",
                        knowledge.id,
                        subscription.subscription_id
                    )
                else:
                    logger.warning(
                        "Could not create/reuse subscription for site %s (webhook URL may not be configured)",
                        key[:30]
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to ensure SharePoint subscription for knowledge %s: %s",
                    knowledge.id,
                    exc,
                    exc_info=True
                )
        else:
            raise ValueError("Unknown integration type")

        # Return both knowledge and job for frontend to track progress
        return knowledge, job

    async def _distribute_knowledge_if_org_space(
        self, knowledge: IntegrationKnowledge, space: "Space"
    ) -> None:
        """Distribute integration knowledge to child spaces if created on org space.

        This mirrors the behavior of collections and websites. When integration knowledge
        is created on an organization space (tenant_space_id IS NULL), it's automatically
        made available to all child spaces via the IntegrationKnowledgesSpaces junction table.
        """
        import sqlalchemy as sa
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from intric.database.tables.integration_knowledge_spaces_table import (
            IntegrationKnowledgesSpaces,
        )

        # Only distribute if this is an org space (no parent tenant_space_id)
        if space.tenant_space_id is not None:
            return

        # Get all child spaces for this tenant
        child_spaces = await self.space_repo.session.execute(
            sa.select(sa.column("id", sa.UUID))
            .select_from(
                sa.table(
                    "spaces",
                    sa.column("id", sa.UUID),
                    sa.column("tenant_id", sa.UUID),
                    sa.column("tenant_space_id", sa.UUID),
                )
            )
            .where(
                sa.and_(
                    sa.column("tenant_id") == space.tenant_id,
                    sa.column("tenant_space_id") == space.id,
                )
            )
        )

        child_space_ids = [row[0] for row in child_spaces.all()]

        if not child_space_ids:
            return

        # Insert distribution records
        ins = pg_insert(IntegrationKnowledgesSpaces).values(
            [
                dict(integration_knowledge_id=knowledge.id, space_id=space_id)
                for space_id in child_space_ids
            ]
        ).on_conflict_do_nothing(
            index_elements=[
                IntegrationKnowledgesSpaces.integration_knowledge_id,
                IntegrationKnowledgesSpaces.space_id,
            ]
        )
        await self.space_repo.session.execute(ins)

    async def remove_knowledge(
        self,
        space_id: "UUID",
        integration_knowledge_id: "UUID",
    ) -> None:
        import sqlalchemy as sa
        from intric.database.tables.integration_knowledge_spaces_table import (
            IntegrationKnowledgesSpaces,
        )

        space = await self.space_repo.one(id=space_id)
        knowledge = space.get_integration_knowledge(
            integration_knowledge_id=integration_knowledge_id
        )
        actor = self.actor_manager.get_space_actor_from_space(space)

        if not actor.can_delete_integration_knowledge_list():
            raise UnauthorizedException()

        # Check if knowledge belongs to this space
        # Only allow deletion from the space where it was created
        if knowledge.space_id != space.id:
            raise UnauthorizedException(
                "Cannot delete knowledge from this space. "
                "This knowledge belongs to another space and must be deleted from there."
            )

        # Remove distribution records if this is an org space
        if space.tenant_space_id is None:
            await self.space_repo.session.execute(
                sa.delete(IntegrationKnowledgesSpaces).where(
                    IntegrationKnowledgesSpaces.integration_knowledge_id == knowledge.id
                )
            )

        subscription_id = knowledge.sharepoint_subscription_id
        if subscription_id and knowledge.integration_type == "sharepoint":
            try:
                user_integration = knowledge.user_integration
                if user_integration.auth_type == "tenant_app":
                    if not user_integration.tenant_app_id:
                        raise BadRequestException("Tenant app ID is required for tenant_app integrations")

                    tenant_app = await self.tenant_sharepoint_app_repo.one(id=user_integration.tenant_app_id)
                    access_token = await self.tenant_app_auth_service.get_access_token(tenant_app)
                    token = SimpleToken(access_token=access_token)
                else:
                    token = await self.oauth_token_repo.one(
                        user_integration_id=knowledge.user_integration.id
                    )

                await self.sharepoint_subscription_service.delete_subscription_if_unused(
                    subscription_id=subscription_id,
                    token=token
                )
                logger.info(
                    "Cleaned up subscription %s (if no longer referenced)",
                    subscription_id
                )
            except Exception as exc:
                logger.warning(
                    "Failed to cleanup subscription %s: %s",
                    subscription_id,
                    exc,
                    exc_info=True
                )

        await self.integration_knowledge_repo.remove(id=knowledge.id)
