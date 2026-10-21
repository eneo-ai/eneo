from typing import TYPE_CHECKING, Optional, Union

from eneo.ai_models.display_name_validation import validate_unique_display_name
from eneo.database.tables.ai_models_table import ForecastModels
from eneo.main.models import NOT_PROVIDED, ModelId, NotProvided, is_provided
from eneo.roles.permissions import Permission, validate_permissions

if TYPE_CHECKING:
    from uuid import UUID

    from eneo.forecast_models.domain.forecast_model import ForecastModel
    from eneo.forecast_models.domain.forecast_model_repo import (
        ForecastModelRepository,
    )
    from eneo.security_classifications.domain.repositories.security_classification_repo_impl import (  # noqa: E501
        SecurityClassificationRepoImpl,
    )
    from eneo.users.user import UserInDB


class ForecastModelCRUDService:
    def __init__(
        self,
        user: "UserInDB",
        forecast_model_repo: "ForecastModelRepository",
        security_classification_repo: Optional["SecurityClassificationRepoImpl"] = None,
    ) -> None:
        super().__init__()
        self.user = user
        self.forecast_model_repo = forecast_model_repo
        self.security_classification_repo = security_classification_repo

    async def get_forecast_models(self) -> list["ForecastModel"]:
        return await self.forecast_model_repo.all()

    @validate_permissions(Permission.ADMIN)
    async def update_forecast_model(
        self,
        model_id: "UUID",
        is_org_enabled: Optional[bool] = None,
        security_classification: Union[ModelId, None, NotProvided] = NOT_PROVIDED,
        display_name: Optional[str] = None,
    ) -> "ForecastModel":
        model = await self.forecast_model_repo.one(model_id)

        if is_org_enabled is not None:
            model.is_org_enabled = is_org_enabled

        if is_provided(security_classification):
            if security_classification is None:
                model.security_classification = None
            else:
                assert self.security_classification_repo is not None
                model.security_classification = (
                    await self.security_classification_repo.one(
                        id=security_classification.id
                    )
                )

        if display_name is not None and display_name != model.nickname:
            await validate_unique_display_name(
                self.forecast_model_repo.session,
                ForecastModels,
                tenant_id=self.user.tenant_id,
                provider_id=model.provider_id,
                nickname=display_name,
                exclude_id=model.id,
            )
            model.nickname = display_name

        await self.forecast_model_repo.update(model)
        return model
