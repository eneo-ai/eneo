from datetime import datetime
from typing import TYPE_CHECKING, Optional, Union, cast
from uuid import UUID

from eneo.ai_models.completion_models.completion_model import (
    CompletionModel as AICompletionModel,
)
from eneo.ai_models.completion_models.completion_model import (
    CompletionModelResponse,
    CompletionModelSparse,
    ModelKwargs,
)
from eneo.apps.apps.api.app_models import InputField, InputFieldType
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.files.audio import AudioMimeTypes
from eneo.files.file_models import File, FileInfo
from eneo.files.image import ImageMimeTypes
from eneo.files.text import TextMimeTypes
from eneo.files.transcriber import Transcriber
from eneo.main.exceptions import BadRequestException
from eneo.main.logging import get_logger
from eneo.main.models import NOT_PROVIDED, NotProvided, is_provided
from eneo.prompts.prompt import Prompt
from eneo.templates.app_template.app_template import AppTemplate

if TYPE_CHECKING:
    from eneo.ai_models.completion_models.completion_model import (
        CompletionModelSparse,
    )
    from eneo.completion_models.domain.completion_model import CompletionModel
    from eneo.transcription_models.domain.transcription_model import (
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
        completion_model: "CompletionModel | CompletionModelSparse | None",
        transcription_model: "TranscriptionModel | None",
        # Non-optional on the domain object; the factory normalises legacy
        # DB NULL into ModelKwargs() so reads, .model_dump() writes and the
        # AppPublic response can rely on it being present.
        completion_model_kwargs: ModelKwargs,
        input_fields: list[InputField],
        attachments: list[File],
        published: bool,
        source_template: AppTemplate | None = None,
        data_retention_days: Optional[int] = None,
        icon_id: Optional[UUID] = None,
    ):
        super().__init__()
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

    def _input_field_types(self) -> list[InputFieldType]:
        return [input_field.type for input_field in self.input_fields]

    def _allowed_mimetype(self, mimetype: str) -> bool:
        def _is_mimetype_allowed_for_field(
            input_field: InputField, mimetype: str
        ) -> bool:
            mimetype_checker = INPUT_FIELD_MIME_TYPES.get(input_field.type)

            if mimetype_checker is None:
                return False

            return mimetype_checker.has_value(mimetype)

        return any(
            _is_mimetype_allowed_for_field(input_field, mimetype)
            for input_field in self.input_fields
        )

    def _max_size(self, mimetype: str) -> int:
        for field_type, max_size in INPUT_FIELD_MAX_SIZE_MAPPING.items():
            mimetype_checker = INPUT_FIELD_MIME_TYPES.get(field_type)
            if mimetype_checker is not None and mimetype_checker.has_value(mimetype):
                return max_size

        return 0

    def _get_prompt_text(self) -> str:
        if self.prompt is None:
            return ""

        return self.prompt.text

    @property
    def input_fields(self) -> list[InputField]:
        return self._input_fields

    @input_fields.setter
    def input_fields(self, input_fields: list[InputField]):
        if len(input_fields) > 1:
            raise BadRequestException(
                f"A {self.__class__.__name__} can only have one input."
            )

        for input_field in input_fields:
            if input_field.type == InputFieldType.IMAGE_UPLOAD and (
                self.completion_model is None or not self.completion_model.vision
            ):
                raise BadRequestException(
                    "Need to have a vision model enabled in order to specify image upload"
                )

        self._input_fields = input_fields

    @property
    def attachments(self) -> list[File]:
        return self._attachments

    @attachments.setter
    def attachments(self, attachments: list[File]):
        for attachment in attachments:
            if attachment.mimetype is None or not TextMimeTypes.has_value(
                attachment.mimetype
            ):
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
        completion_model: "CompletionModel | CompletionModelSparse | None" = None,
        completion_model_kwargs: ModelKwargs | None = None,
        input_fields: list[InputField] | None = None,
        attachments: list[File] | None = None,
        published: bool | None = None,
        transcription_model: "TranscriptionModel | None" = None,
        data_retention_days: Union[int, None, NotProvided] = NOT_PROVIDED,
        icon_id: Union[UUID, None, NotProvided] = NOT_PROVIDED,
    ) -> None:
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

        if is_provided(data_retention_days):
            self.data_retention_days = data_retention_days

        if is_provided(icon_id):
            self.icon_id = icon_id

    def is_valid_input(self, files: list[FileInfo], text: str | None = None) -> bool:
        if not files and not text:
            return False
        if files and text:
            return False

        # Validate files
        if files:
            for file in files:
                if file.mimetype is None:
                    return False

                if not self._allowed_mimetype(file.mimetype):
                    return False

                if file.size > self._max_size(file.mimetype):
                    return False

                # Check if there are audio files that require a transcription model
                if (
                    AudioMimeTypes.has_value(file.mimetype)
                    and not self.transcription_model
                ):
                    return False

            total_size = sum(file.size for file in files)
            if total_size > 200 * 1024 * 1024:  # 200 MB
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

        return False

    async def run(
        self,
        files: list[File],
        text: str | None,
        completion_service: CompletionService,
        transcriber: Transcriber,
    ) -> CompletionModelResponse:
        if text is None:
            text = ""

        audio_files = [
            file
            for file in files
            if file.mimetype is not None and AudioMimeTypes.has_value(file.mimetype)
        ]

        transcription_model = self.transcription_model
        if audio_files and transcription_model is None:
            raise BadRequestException(
                "Need to have a transcription model enabled in order to process audio"
            )

        transcriptions = [
            await transcriber.transcribe(
                file,
                transcription_model,  # pyright: ignore[reportArgumentType]  # narrowed: audio_files guard above ensures non-None
            )
            for file in audio_files
        ]

        text_files = [
            file
            for file in files
            if file.mimetype is not None and TextMimeTypes.has_value(file.mimetype)
        ]

        image_files = [
            file
            for file in files
            if file.mimetype is not None and ImageMimeTypes.has_value(file.mimetype)
        ]

        return await completion_service.get_response(
            text_input=text,
            transcription_inputs=transcriptions,
            files=image_files + text_files,
            model=cast(AICompletionModel, self.completion_model),
            prompt=self._get_prompt_text(),
            prompt_files=self.attachments,
            model_kwargs=self.completion_model_kwargs,
        )
