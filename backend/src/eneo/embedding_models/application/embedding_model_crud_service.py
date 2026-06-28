from typing import TYPE_CHECKING, Union

from eneo.main.models import NOT_PROVIDED, ModelId, is_provided
from eneo.roles.permissions import Permission, validate_permissions

if TYPE_CHECKING:
    from uuid import UUID

    from eneo.embedding_models.domain.embedding_model_repo import (
        EmbeddingModelRepository,
    )
    from eneo.main.models import NotProvided
    from eneo.security_classifications.domain.repositories.security_classification_repo_impl import (  # noqa: E501
        SecurityClassificationRepoImpl,
    )
    from eneo.users.user import UserInDB


class EmbeddingModelCRUDService:
    def __init__(
        self,
        user: "UserInDB",
        embedding_model_repo: "EmbeddingModelRepository",
        security_classification_repo: "SecurityClassificationRepoImpl",
    ) -> None:
        super().__init__()
        self.embedding_model_repo = embedding_model_repo
        self.security_classification_repo = security_classification_repo
        self.user = user

    async def get_embedding_models(self):
        return await self.embedding_model_repo.all()

    async def get_embedding_model(self, model_id: "UUID"):
        return await self.embedding_model_repo.one(model_id=model_id)

    @validate_permissions(Permission.ADMIN)
    async def update_embedding_model(
        self,
        model_id: "UUID",
        is_org_enabled: Union[bool, "NotProvided"],
        security_classification: Union[ModelId, None, "NotProvided"] = NOT_PROVIDED,
    ):
        embedding_model = await self.embedding_model_repo.one(model_id=model_id)

        if is_provided(security_classification):
            if security_classification is None:
                embedding_model.security_classification = None
            else:
                em_security_classification = (
                    await self.security_classification_repo.one(
                        id=security_classification.id
                    )
                )
                embedding_model.security_classification = em_security_classification

        embedding_model.update(is_org_enabled=is_org_enabled)

        return await self.embedding_model_repo.update(embedding_model)
