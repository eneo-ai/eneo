from typing import TYPE_CHECKING, Optional, Union

from eneo.main.models import NOT_PROVIDED, ModelId, NotProvided, is_provided
from eneo.roles.permissions import Permission, validate_permissions

if TYPE_CHECKING:
    from uuid import UUID

    from eneo.rerank_models.domain.rerank_model import RerankModel
    from eneo.rerank_models.domain.rerank_model_repo import RerankModelRepository
    from eneo.security_classifications.domain.repositories.security_classification_repo_impl import (  # noqa: E501
        SecurityClassificationRepoImpl,
    )
    from eneo.users.user import UserInDB


class RerankModelCRUDService:
    def __init__(
        self,
        user: "UserInDB",
        rerank_model_repo: "RerankModelRepository",
        security_classification_repo: Optional["SecurityClassificationRepoImpl"] = None,
    ) -> None:
        super().__init__()
        self.rerank_model_repo = rerank_model_repo
        self.user = user
        self.security_classification_repo = security_classification_repo

    async def get_rerank_models(self) -> list["RerankModel"]:
        return await self.rerank_model_repo.all()

    @validate_permissions(Permission.ADMIN)
    async def update_rerank_model(
        self,
        model_id: "UUID",
        is_org_enabled: Optional[bool],
        is_org_default: Optional[bool],
        security_classification: Union[ModelId, None, NotProvided] = NOT_PROVIDED,
    ) -> "RerankModel":
        rerank_model = await self.rerank_model_repo.one(model_id=model_id)

        if is_org_enabled is not None:
            rerank_model.is_org_enabled = is_org_enabled

        if is_org_default is not None:
            rerank_model.is_org_default = is_org_default

        if is_provided(security_classification):
            if security_classification is None:
                classification = None
            else:
                assert self.security_classification_repo is not None
                classification = await self.security_classification_repo.one(
                    id=security_classification.id
                )
            rerank_model.security_classification = classification

        await self.rerank_model_repo.update(rerank_model)
        return rerank_model
