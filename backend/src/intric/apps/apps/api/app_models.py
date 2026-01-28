from enum import Enum
from typing import Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from intric.ai_models.completion_models.completion_model import (
    CompletionModelSparse,
    ModelKwargs,
)
from intric.files.file_models import FilePublic, FileRestrictions
from intric.main.models import NOT_PROVIDED, InDB, ModelId, NotProvided, ResourcePermissionsMixin
from intric.prompts.api.prompt_models import PromptCreate, PromptPublic
from intric.transcription_models.presentation import TranscriptionModelPublic


class InputFieldType(str, Enum):
    TEXT_FIELD = "text-field"
    TEXT_UPLOAD = "text-upload"
    AUDIO_UPLOAD = "audio-upload"
    AUDIO_RECORDER = "audio-recorder"
    IMAGE_UPLOAD = "image-upload"

    @classmethod
    def contains_input_type(cls, input_type: str) -> bool:
        return input_type in cls._value2member_map_


class InputField(BaseModel):
    type: InputFieldType
    description: str | None = None

    model_config = ConfigDict(from_attributes=True)


class InputFieldPublic(InputField, FileRestrictions):
    pass


# App models


class AppCreateRequest(BaseModel):
    name: str


class AppPublic(AppCreateRequest, InDB, ResourcePermissionsMixin):
    description: str | None
    input_fields: list[InputFieldPublic]
    attachments: list[FilePublic]
    prompt: PromptPublic | None
    completion_model: CompletionModelSparse | None = None
    completion_model_kwargs: ModelKwargs
    allowed_attachments: FileRestrictions
    published: bool
    transcription_model: TranscriptionModelPublic | None = None
    data_retention_days: Optional[int] = None
    icon_id: Optional[UUID] = Field(
        default=None,
        description="Icon ID referencing an uploaded icon",
    )


class AppUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    input_fields: Optional[list[InputField]] = None
    attachments: Optional[list[ModelId]] = None
    prompt: Optional[PromptCreate] = None
    completion_model: Optional[ModelId] = None
    completion_model_kwargs: Optional[ModelKwargs] = None
    transcription_model: Optional[ModelId] = None
    data_retention_days: Union[int, None, NotProvided] = NOT_PROVIDED
    icon_id: Union[UUID, None, NotProvided] = Field(
        default=NOT_PROVIDED,
        description="Icon ID referencing an uploaded icon. Set to null to remove.",
    )
