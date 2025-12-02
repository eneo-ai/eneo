from datetime import datetime
from typing import TYPE_CHECKING, Optional, Union
from uuid import UUID

from intric.ai_models.completion_models.completion_model import (
    CompletionModelSparse,
    ModelKwargs,
)
from intric.apps.apps.api.app_models import InputField, InputFieldType
from intric.completion_models.infrastructure.completion_service import CompletionService
from intric.files.audio import AudioMimeTypes
from intric.files.file_models import File, FileInfo
from intric.files.image import ImageMimeTypes
from intric.files.text import TextMimeTypes
from intric.files.transcriber import Transcriber
from intric.main.exceptions import BadRequestException
from intric.main.logging import get_logger
from intric.main.models import NOT_PROVIDED, NotProvided
from intric.prompts.prompt import Prompt
from intric.templates.app_template.app_template import AppTemplate

if TYPE_CHECKING:
    from intric.completion_models.domain import CompletionModel
    from intric.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )

logger = get_logger(__name__)

INPUT_FIELD_MIME_TYPES = {
    InputFieldType.TEXT_UPLOAD: TextMimeTypes,
    InputFieldType.IMAGE_UPLOAD: ImageMimeTypes,
    InputFieldType.AUDIO_UPLOAD: AudioMimeTypes,
    InputFieldType.AUDIO_RECORDER: AudioMimeTypes,
}

INPUT_FIELD_MAX_SIZE_MAPPING = {
    InputFieldType.TEXT_FIELD: 0,
    InputFieldType.TEXT_UPLOAD: 26214400,
    InputFieldType.IMAGE_UPLOAD: 20971520,
    InputFieldType.AUDIO_UPLOAD: 209715200,
    InputFieldType.AUDIO_RECORDER: 209715200,
}

MAX_FILES_MAPPING = {
    InputFieldType.TEXT_FIELD: 0,
    InputFieldType.TEXT_UPLOAD: 3,
    InputFieldType.AUDIO_UPLOAD: 1,
    InputFieldType.AUDIO_RECORDER: 1,
    InputFieldType.IMAGE_UPLOAD: 2,
}


class App:
    def __init__(
        self,
        created_at: datetime | None,
        updated_at: datetime | None,
        id: UUID | None,
        tenant_id: UUID,
        user_id: UUID,
        space_id: UUID,
        name: str,
        description: str | None,
        prompt: Prompt | None,
        completion_model: "CompletionModel",
        transcription_model: "TranscriptionModel",
        completion_model_kwargs: ModelKwargs | None,
        input_fields: list[InputField],
        attachments: list[FileInfo],
        published: bool,
        source_template: AppTemplate | None = None,
        data_retention_days: Optional[int] = None,
        icon_id: Optional[UUID] = None,
    ):
        self._input_fields = input_fields
        self._attachments = attachments

        self.created_at = created_at
        self.updated_at = updated_at
        self.id = id
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.space_id = space_id
        self.name = name
        self.description = description
        self.prompt = prompt
        self.completion_model = completion_model
        self.completion_model_kwargs = completion_model_kwargs
        self.published = published
        self.source_template = source_template
        self.transcription_model = transcription_model
        self.data_retention_days = data_retention_days
        self.icon_id = icon_id

    def _input_field_types(self):
        return [input_field.type for input_field in self.input_fields]

    def _allowed_mimetype(self, mimetype: str):
        def _is_mimetype_allowed_for_field(input_field: InputField, mimetype):
            mimetype_checker = INPUT_FIELD_MIME_TYPES.get(input_field.type)

            if mimetype_checker is None:
                return False

            return mimetype_checker.has_value(mimetype)

        return any(
            _is_mimetype_allowed_for_field(input_field, mimetype)
            for input_field in self.input_fields
        )

    def _max_size(self, mimetype: str):
        for field_type, max_size in INPUT_FIELD_MAX_SIZE_MAPPING.items():
            mimetype_checker = INPUT_FIELD_MIME_TYPES.get(field_type)
            if mimetype_checker is not None and mimetype_checker.has_value(mimetype):
                return max_size

        return 0

    def _get_prompt_text(self):
        if self.prompt is None:
            return ""

        return self.prompt.text

    @property
    def input_fields(self):
        return self._input_fields

    @input_fields.setter
    def input_fields(self, input_fields: list[InputField]):
        if len(input_fields) > 1:
            raise BadRequestException(f"A {self.__class__.__name__} can only have one input.")

        for input_field in input_fields:
            if input_field.type == InputFieldType.IMAGE_UPLOAD and not self.completion_model.vision:
                raise BadRequestException(
                    "Need to have a vision model enabled in order to specify image upload"
                )

        self._input_fields = input_fields

    @property
    def attachments(self):
        return self._attachments

    @attachments.setter
    def attachments(self, attachments: list[FileInfo]):
        for attachment in attachments:
            if not TextMimeTypes.has_value(attachment.mimetype):
                raise BadRequestException("Attachements can only be text files")

        if sum(attachment.size for attachment in attachments) > 26214400:
            raise BadRequestException("Files too large!")

        self._attachments = attachments

    def update(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        prompt: Prompt | None = None,
        completion_model: CompletionModelSparse | None = None,
        completion_model_kwargs: ModelKwargs | None = None,
        input_fields: list[InputField] | None = None,
        attachments: list[FileInfo] | None = None,
        published: bool | None = None,
        transcription_model: "TranscriptionModel" = None,
        data_retention_days: Union[int, None, NotProvided] = NOT_PROVIDED,
        icon_id: Union[UUID, None, NotProvided] = NOT_PROVIDED,
    ):
        if name is not None:
            self.name = name

        if description is not None:
            self.description = description

        if prompt is not None:
            self.prompt = prompt

        if completion_model is not None:
            self.completion_model = completion_model

        if completion_model_kwargs is not None:
            self.completion_model_kwargs = completion_model_kwargs

        if transcription_model is not None:
            self.transcription_model = transcription_model

        if input_fields is not None:
            self.input_fields = input_fields

        if attachments is not None:
            self.attachments = attachments

        if published is not None:
            self.published = published

        if data_retention_days is not NOT_PROVIDED:
            self.data_retention_days = data_retention_days

        if icon_id is not NOT_PROVIDED:
            self.icon_id = icon_id

    def is_valid_input(self, files: list[FileInfo], text: str | None = None):
        if not files and not text:
            return False
        if files and text:
            return False

        # Validate files
        if files:
            for file in files:
                if not self._allowed_mimetype(file.mimetype):
                    return False

                if file.size > self._max_size(file.mimetype):
                    return False

                # Check if there are audio files that require a transcription model
                if AudioMimeTypes.has_value(file.mimetype) and not self.transcription_model:
                    return False

            total_size = sum(file.size for file in files)
            if total_size > 200 * 1024 * 1024:  # 200 MiB
                return False

            for input_field in self.input_fields:
                max_files = MAX_FILES_MAPPING.get(input_field.type, 0)

                if len(files) > max_files:
                    return False

            return True

        # Validate text
        if text:
            if InputFieldType.TEXT_FIELD not in self._input_field_types():
                return False

            if len(text) > 10000:
                return False

            return True

    async def run(
        self,
        files: list[File],
        text: str | None,
        completion_service: CompletionService,
        transcriber: Transcriber,
    ):
        if text is None:
            text = ""

        audio_files = [file for file in files if AudioMimeTypes.has_value(file.mimetype)]

        transcriptions = [
            await transcriber.transcribe(file, self.transcription_model) for file in audio_files
        ]

        text_files = [file for file in files if TextMimeTypes.has_value(file.mimetype)]

        image_files = [file for file in files if ImageMimeTypes.has_value(file.mimetype)]

        return await completion_service.get_response(
            text_input=text,
            transcription_inputs=transcriptions,
            files=image_files + text_files,
            model=self.completion_model,
            prompt=self._get_prompt_text(),
            prompt_files=self.attachments,
            model_kwargs=self.completion_model_kwargs,
        )
