from typing import List

from pydantic import BaseModel

from eneo.ai_models.completion_models.completion_model import (
    CompletionModelSecurityStatus,
)
from eneo.embedding_models.presentation.embedding_model_models import (
    EmbeddingModelSecurityStatus,
)
from eneo.transcription_models.presentation.transcription_model_models import (
    TranscriptionModelSecurityStatus,
)


class ModelsPresentation(BaseModel):
    """Presentation model for all types of AI models."""

    completion_models: List[CompletionModelSecurityStatus]
    embedding_models: List[EmbeddingModelSecurityStatus]
    transcription_models: List[TranscriptionModelSecurityStatus]
