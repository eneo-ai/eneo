from typing import TYPE_CHECKING, Optional, Union

from eneo.main.datetime_utils import datetime_or_utc_min
from eneo.main.exceptions import UnauthorizedException
from eneo.main.models import NOT_PROVIDED, ModelId, NotProvided, is_provided
from eneo.roles.permissions import Permission, validate_permissions

if TYPE_CHECKING:
    from uuid import UUID

    from eneo.security_classifications.domain.repositories.security_classification_repo_impl import (  # noqa: E501
        SecurityClassificationRepoImpl,
    )
    from eneo.transcription_models.domain import TranscriptionModelRepository
    from eneo.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )
    from eneo.users.user import UserInDB


class TranscriptionModelCRUDService:
    def __init__(
        self,
        user: "UserInDB",
        transcription_model_repo: "TranscriptionModelRepository",
        security_classification_repo: Optional["SecurityClassificationRepoImpl"] = None,
    ) -> None:
        super().__init__()
        self.transcription_model_repo = transcription_model_repo
        self.user = user
        self.security_classification_repo = security_classification_repo

    async def get_transcription_models(self):
        return await self.transcription_model_repo.all()

    async def get_transcription_model(self, model_id: "UUID"):
        transcription_model = await self.transcription_model_repo.one(model_id=model_id)

        if not transcription_model.can_access:
            raise UnauthorizedException()

        return transcription_model

    async def get_available_transcription_models(self):
        transcription_models = await self.transcription_model_repo.all()

        return [model for model in transcription_models if model.can_access]

    async def get_default_transcription_model(self) -> Optional["TranscriptionModel"]:
        transcription_models = await self.get_available_transcription_models()

        # First try to get the org default model
        for model in transcription_models:
            if model.is_org_default:
                return model

        # Otherwise get the latest model
        sorted_models = sorted(
            transcription_models,
            key=lambda model: datetime_or_utc_min(model.created_at),
            reverse=True,
        )

        # If no models are available
        if not sorted_models:
            return None

        return sorted_models[0]

    @validate_permissions(Permission.ADMIN)
    async def update_transcription_model(
        self,
        model_id: "UUID",
        is_org_enabled: Optional[bool],
        is_org_default: Optional[bool],
        security_classification: Union[ModelId, None, NotProvided] = NOT_PROVIDED,
    ):
        transcription_model = await self.transcription_model_repo.one(model_id=model_id)

        if is_org_enabled is not None:
            transcription_model.is_org_enabled = is_org_enabled

        if is_org_default is not None:
            transcription_model.is_org_default = is_org_default

        if is_provided(security_classification):
            if security_classification is None:
                tm_security_classification = None
            else:
                assert self.security_classification_repo is not None
                tm_security_classification = (
                    await self.security_classification_repo.one(
                        id=security_classification.id
                    )
                )
            transcription_model.security_classification = tm_security_classification

        await self.transcription_model_repo.update(transcription_model)

        return transcription_model
