from typing import TYPE_CHECKING
from uuid import UUID

from intric.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from intric.integration.presentation.models import (
    ConfluenceContentTaskParam,
    SharepointContentTaskParam,
)
from intric.jobs.job_models import Task
from intric.main.exceptions import BadRequestException, UnauthorizedException
from intric.main.logging import get_logger

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
    from intric.jobs.job_service import JobService
    from intric.integration.infrastructure.sharepoint_subscription_service import SharePointSubscriptionService
    from intric.spaces.space_repo import SpaceRepository
    from intric.users.user import UserInDB


logger = get_logger(__name__)


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

    async def create_space_integration_knowledge(
        self,
        user_integration_id: UUID,
        name: str,
        embedding_model_id: UUID,
        space_id: UUID,
        key: str,
        url: str,
    ) -> IntegrationKnowledge:
        space = await self.space_repo.one(id=space_id)
        if not space.is_embedding_model_in_space(embedding_model_id=embedding_model_id):
            raise BadRequestException("No valid embedding model")

        user_integration = await self.user_integration_repo.one(id=user_integration_id)
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
        )
        knowledge = await self.integration_knowledge_repo.add(obj=obj)
        token = await self.oauth_token_repo.one(user_integration_id=user_integration_id)

        if token.token_type.is_confluence:
            await self.job_service.queue_job(
                task=Task.PULL_CONFLUENCE_CONTENT,
                name=name,
                task_params=ConfluenceContentTaskParam(
                    user_id=self.user.id,
                    id=user_integration_id,
                    token_id=token.id,
                    space_key=key,
                    integration_knowledge_id=knowledge.id,
                ),
            )
        elif token.token_type.is_sharepoint:
            await self.job_service.queue_job(
                task=Task.PULL_SHAREPOINT_CONTENT,
                name=name,
                task_params=SharepointContentTaskParam(
                    user_id=self.user.id,
                    id=user_integration_id,
                    token_id=token.id,
                    integration_knowledge_id=knowledge.id,
                    site_id=key,
                ),
            )
            try:
                knowledge = await self.sharepoint_subscription_service.ensure_subscription(
                    token=token, knowledge=knowledge
                )
            except Exception as exc:
                logger.warning(
                    "Failed to register SharePoint subscription for knowledge %s: %s",
                    knowledge.id,
                    exc,
                )
        else:
            raise ValueError("Unknown integration type")

        return knowledge

    async def remove_knowledge(
        self,
        space_id: "UUID",
        integration_knowledge_id: "UUID",
    ) -> None:
        space = await self.space_repo.one(id=space_id)
        knowledge = space.get_integration_knowledge(
            integration_knowledge_id=integration_knowledge_id
        )
        actor = self.actor_manager.get_space_actor_from_space(space)

        if not actor.can_delete_integration_knowledge_list():
            raise UnauthorizedException()

        await self.integration_knowledge_repo.remove(id=knowledge.id)
