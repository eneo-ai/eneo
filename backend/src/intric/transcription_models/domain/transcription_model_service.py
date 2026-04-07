from datetime import datetime
from typing import Optional

from intric.transcription_models.domain.transcription_model import TranscriptionModel
from intric.transcription_models.domain.transcription_model_repo import (
    TranscriptionModelRepository,
)


class TranscriptionModelService:
    def __init__(self, transcription_model_repo: TranscriptionModelRepository) -> None:
        super().__init__()
        self.transcription_model_repo = transcription_model_repo

    async def get_default_model(self) -> Optional[TranscriptionModel]:
        transcription_models = await self.transcription_model_repo.all()
        available_models = [model for model in transcription_models if model.can_access]

        # First try to get the org default model
        for model in available_models:
            if model.is_org_default:
                return model

        # Otherwise get the latest model
        sorted_models: list[TranscriptionModel] = sorted(
            available_models,
            key=lambda model: model.created_at or datetime.min,
            reverse=True,
        )

        if not sorted_models:
            return None

        return sorted_models[0]
