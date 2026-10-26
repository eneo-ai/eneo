from typing import TYPE_CHECKING, Optional, Union

from eneo.ai_models.display_name_validation import validate_unique_display_name
from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.database.tables.ai_models_table import ForecastModels
from eneo.main.models import NOT_PROVIDED, ModelId, NotProvided, is_provided
from eneo.roles.permissions import Permission, validate_permissions

if TYPE_CHECKING:
    from uuid import UUID

    from eneo.audit.application.audit_service import AuditService
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
        audit_service: Optional["AuditService"] = None,
    ) -> None:
        super().__init__()
        self.user = user
        self.forecast_model_repo = forecast_model_repo
        self.security_classification_repo = security_classification_repo
        self.audit_service = audit_service

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
        """Turn the model on or off, classify or rename it, in one audit entry.

        The row is read under its lock and only the columns that change are
        written, so a concurrent update is never undone, and the audit entry
        compares against the state this update replaces.
        """
        model = await self.forecast_model_repo.one(model_id, for_update=True)
        values: dict[str, object] = {}
        changes: dict[str, object] = {}

        if is_org_enabled is not None and is_org_enabled != model.is_org_enabled:
            changes["is_org_enabled"] = {
                "old": model.is_org_enabled,
                "new": is_org_enabled,
            }
            values["is_enabled"] = is_org_enabled
            model.is_org_enabled = is_org_enabled

        if is_provided(security_classification):
            old = model.security_classification
            new = None
            if security_classification is not None:
                assert self.security_classification_repo is not None
                new = await self.security_classification_repo.one(
                    id=security_classification.id
                )
            if (old.id if old else None) != (new.id if new else None):
                changes["security_classification"] = {
                    "old": old.name if old else None,
                    "new": new.name if new else None,
                }
                values["security_classification_id"] = new.id if new else None
                model.security_classification = new

        if display_name is not None and display_name != model.nickname:
            await validate_unique_display_name(
                self.forecast_model_repo.session,
                ForecastModels,
                tenant_id=self.user.tenant_id,
                provider_id=model.provider_id,
                nickname=display_name,
                exclude_id=model.id,
            )
            changes["display_name"] = {"old": model.nickname, "new": display_name}
            values["nickname"] = display_name
            model.nickname = display_name

        if values:
            await self.forecast_model_repo.update(model.id, values)
        if changes and self.audit_service is not None:
            await self.audit_service.log_async(
                tenant_id=self.user.tenant_id,
                user=self.user,
                action=ActionType.FORECAST_MODEL_UPDATED,
                entity_type=EntityType.FORECAST_MODEL,
                entity_id=model.id,
                description=f"Updated settings for forecast model {model.nickname}",
                metadata=AuditMetadata.standard(
                    actor=self.user, target=model, changes=changes
                ),
            )
        return model
