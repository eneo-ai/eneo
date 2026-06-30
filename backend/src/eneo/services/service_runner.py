from typing import cast

import pydantic

from eneo.assistants.references import ReferencesService
from eneo.collections.domain.collection import Collection
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.completion_models.infrastructure.context_builder import count_tokens
from eneo.files.file_models import FilePublic
from eneo.files.file_service import FileService
from eneo.main.exceptions import PydanticParseError
from eneo.main.logging import get_logger
from eneo.main.models import ModelId
from eneo.questions.question import QuestionAdd
from eneo.questions.questions_repo import QuestionRepository
from eneo.services.output_parsing.output_parser import OutputParserBase
from eneo.services.service import RunnerResult, Service
from eneo.users.user import UserInDB

logger = get_logger(__name__)


class ServiceRunner:
    def __init__(
        self,
        user: UserInDB,
        service: Service,
        completion_service: CompletionService,
        file_service: FileService,
        output_parser: OutputParserBase,
        references_service: ReferencesService,
        question_repo: QuestionRepository,
        prompt: str,
    ) -> None:
        super().__init__()
        self.user = user
        self.service = service
        self.completion_service = completion_service
        self.output_parser = output_parser
        self.references_service = references_service
        self.question_repo = question_repo
        self.prompt = prompt
        self.file_service = file_service

    async def run(
        self,
        input: str,
        file_ids: list[ModelId] | None = None,
    ) -> RunnerResult:
        # Get the relevant texts
        datastore_result = await self.references_service.get_references(
            input, collections=cast(list[Collection], self.service.groups)
        )

        effective_file_ids = file_ids or []
        files = await self.file_service.get_files_by_ids(
            [file.id for file in effective_file_ids]
        )

        assert self.service.completion_model is not None, (
            "Service must have a completion model"
        )

        # Document-derived images (e.g. rendered PDF pages) enrich the
        # completion payload only — the persisted question and the returned
        # files stay the user's own uploads.
        completion_files = files
        if self.service.completion_model.vision:
            completion_files = await self.file_service.with_derived_images(files)

        # Query the AI models
        ai_response = await self.completion_service.get_response(
            model=self.service.completion_model,  # pyright: ignore[reportArgumentType]  # two CompletionModel classes coexist: ai_models.completion_model vs completion_models.domain; structural mismatch, works at runtime
            text_input=input,
            files=completion_files,
            prompt=self.prompt,
            info_blob_chunks=datastore_result.chunks,
            model_kwargs=self.service.completion_model_kwargs,
        )

        logger.debug(f"Service response: '{ai_response.completion.text}'")  # type: ignore[union-attr]

        try:
            output = self.output_parser.parse(ai_response.completion.text)  # type: ignore[union-attr]
        except pydantic.ValidationError as e:
            raise PydanticParseError("Error parsing output.") from e

        # Prefer actual provider token counts, fall back to tiktoken estimates
        answer = output.to_string()

        if ai_response.usage and ai_response.usage.prompt_tokens is not None:
            num_tokens_question = ai_response.usage.prompt_tokens
            input_source = "provider"
        else:
            num_tokens_question = ai_response.total_token_count
            input_source = "litellm"

        if ai_response.usage and ai_response.usage.completion_tokens is not None:
            num_tokens_answer = ai_response.usage.completion_tokens
            output_source = "provider"
        else:
            model_name = (
                self.service.completion_model.name
                if self.service.completion_model
                else ""
            )
            num_tokens_answer = count_tokens(answer, model_name)
            output_source = "litellm"

        logger.info(
            f"[TokenUsage] service={self.service.id} — "
            f"input={num_tokens_question} ({input_source}), "
            f"output={num_tokens_answer} ({output_source})"
        )

        # Save
        question = QuestionAdd(
            tenant_id=self.user.tenant_id,
            question=input,
            answer=answer,
            num_tokens_question=num_tokens_question,
            num_tokens_answer=num_tokens_answer,
            completion_model_id=self.service.completion_model.id,
            service_id=self.service.id,
        )
        await self.question_repo.add(
            question,
            info_blob_chunks=datastore_result.no_duplicate_chunks,
            files=files,
        )

        return RunnerResult(
            result=cast(
                bool | list[object] | dict[str, object] | str, output.to_value()
            ),
            datastore_result=datastore_result,
            files=cast(list[FilePublic], files),
        )
