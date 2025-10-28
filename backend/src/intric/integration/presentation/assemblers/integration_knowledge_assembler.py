from typing import TYPE_CHECKING

from intric.ai_models.embedding_models.embedding_model import (
    EmbeddingModelPublicLegacy,
)
from intric.integration.presentation.models import (
    IntegrationKnowledgeMetaData,
    IntegrationKnowledgePublic,
)
from intric.jobs.job_models import Task

if TYPE_CHECKING:
    from intric.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )


class IntegrationKnowledgeAssembler:
    @classmethod
    def to_space_knowledge_model(
        cls,
        item: "IntegrationKnowledge",
    ) -> IntegrationKnowledgePublic:
        embedding_model = EmbeddingModelPublicLegacy.model_validate(item.embedding_model)
        integration_type = item.user_integration.tenant_integration.integration.integration_type

        if integration_type == "confluence":
            task = Task.PULL_CONFLUENCE_CONTENT
        elif integration_type == "sharepoint":
            task = Task.PULL_SHAREPOINT_CONTENT
        else:
            raise ValueError("Unknown integration type")
        return IntegrationKnowledgePublic(
            id=item.id,
            name=item.name,
            url=item.url,
            tenant_id=item.tenant_id,
            space_id=item.space_id,
            user_integration_id=item.user_integration.id,
            embedding_model=embedding_model,
            permissions=getattr(item, "permissions", []),
            site_id=getattr(item, "site_id", None),
            sharepoint_subscription_id=getattr(item, "sharepoint_subscription_id", None),
            sharepoint_subscription_expires_at=getattr(item, "sharepoint_subscription_expires_at", None),
            metadata=IntegrationKnowledgeMetaData(
                size=item.size,
                last_sync_summary=getattr(item, "last_sync_summary", None),
                last_synced_at=getattr(item, "last_synced_at", None),
                sharepoint_subscription_expires_at=getattr(item, "sharepoint_subscription_expires_at", None),
            ),
            integration_type=integration_type,
            task=task,
        )

    @classmethod
    def to_knowledge_model_list(
        cls, items: list["IntegrationKnowledge"]
    ) -> list[IntegrationKnowledgePublic]:
        return [cls.to_space_knowledge_model(i) for i in items]
