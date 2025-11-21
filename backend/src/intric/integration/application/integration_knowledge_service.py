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
    from intric.spaces.space import Space
    from intric.spaces.space_repo import SpaceRepository
    from intric.users.user import UserInDB


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
    ):
        self.job_service = job_service
        self.user = user
        self.oauth_token_repo = oauth_token_repo
        self.space_repo = space_repo
        self.integration_knowledge_repo = integration_knowledge_repo
        self.embedding_model_repo = embedding_model_repo
        self.user_integration_repo = user_integration_repo
        self.actor_manager = actor_manager

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
        obj = IntegrationKnowledge(
            name=name,
            space_id=space_id,
            embedding_model=embedding_model,
            user_integration=user_integration,
            tenant_id=self.user.tenant_id,
            url=url,
        )
        knowledge = await self.integration_knowledge_repo.add(obj=obj)

        # Distribute to child spaces if created on org space
        await self._distribute_knowledge_if_org_space(knowledge, space)

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
        else:
            raise ValueError("Unknown integration type")

        return knowledge

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

        # Remove distribution records if this is an org space
        if space.tenant_space_id is None:
            await self.space_repo.session.execute(
                sa.delete(IntegrationKnowledgesSpaces).where(
                    IntegrationKnowledgesSpaces.integration_knowledge_id == knowledge.id
                )
            )

        await self.integration_knowledge_repo.remove(id=knowledge.id)
