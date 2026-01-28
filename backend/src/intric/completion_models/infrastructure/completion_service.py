from __future__ import annotations

import json
from typing import TYPE_CHECKING, AsyncGenerator, Optional

from intric.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModel,
    CompletionModelResponse,
    ModelKwargs,
    ResponseType,
)
from intric.completion_models.infrastructure.context_builder import ContextBuilder
from intric.files.file_models import File
from intric.info_blobs.info_blob import InfoBlobChunkInDBWithScore
from intric.main.config import SETTINGS, Settings, get_settings
from intric.main.logging import get_logger
from intric.sessions.session import SessionInDB
from intric.vision_models.infrastructure.flux_ai import FluxAdapter

if TYPE_CHECKING:
    from intric.completion_models.infrastructure.adapters.base_adapter import (
        CompletionModelAdapter,
    )
    from intric.completion_models.infrastructure.web_search import WebSearchResult
    from intric.database.database import AsyncSession
    from intric.main.container.container import Container
    from intric.settings.encryption_service import EncryptionService
    from intric.tenants.tenant import TenantInDB

logger = get_logger(__name__)


async def generate_image(prompt: str):
    flux = FluxAdapter()

    return await flux.generate_image(prompt=prompt)


class CompletionService:
    def __init__(
        self,
        context_builder: ContextBuilder,
        tenant: Optional["TenantInDB"] = None,
        config: Optional[Settings] = None,
        encryption_service: Optional["EncryptionService"] = None,
        session: Optional["AsyncSession"] = None,
    ):
        self.context_builder = context_builder
        self.tenant = tenant
        self.config = config or SETTINGS
        self.encryption_service = encryption_service
        self.session = session

    async def _get_adapter(self, model: CompletionModel) -> "CompletionModelAdapter":
        """
        Get the adapter for the given model.

        All models must have a provider_id linking to a ModelProvider.
        Uses TenantModelAdapter which routes through LiteLLM.
        """
        import sqlalchemy as sa
        from intric.database.tables.model_providers_table import ModelProviders
        from intric.model_providers.infrastructure.tenant_model_credential_resolver import (
            TenantModelCredentialResolver,
        )
        from intric.completion_models.infrastructure.adapters.tenant_model_adapter import (
            TenantModelAdapter,
        )

        # All models must have provider_id
        if not hasattr(model, 'provider_id') or not model.provider_id:
            raise ValueError(
                f"Model '{model.name}' is missing required provider_id. "
                "All models must be associated with a ModelProvider."
            )

        # Check if session is available
        if not self.session:
            logger.error(
                "Model requires database session but none available",
                extra={
                    "model_id": str(model.id) if hasattr(model, 'id') else None,
                    "model_name": model.name,
                    "provider_id": str(model.provider_id),
                    "tenant_id": str(self.tenant.id) if self.tenant else None,
                }
            )
            raise ValueError(
                f"Model '{model.name}' requires database session to load provider credentials. "
                "Please ensure the CompletionService is initialized with a database session."
            )

        # Load provider data from database
        stmt = sa.select(ModelProviders).where(ModelProviders.id == model.provider_id)
        result = await self.session.execute(stmt)
        provider_db = result.scalar_one_or_none()

        if provider_db is None:
            raise ValueError(f"Model provider {model.provider_id} not found")

        if not provider_db.is_active:
            raise ValueError(f"Model provider {model.provider_id} is not active")

        # Create credential resolver
        credential_resolver = TenantModelCredentialResolver(
            provider_id=provider_db.id,
            provider_type=provider_db.provider_type,
            credentials=provider_db.credentials,
            config=provider_db.config,
            encryption_service=self.encryption_service,
        )

        logger.info(
            f"Using TenantModelAdapter for model '{model.name}'",
            extra={
                "model_id": str(model.id) if hasattr(model, 'id') else None,
                "model_name": model.name,
                "provider_id": str(model.provider_id),
                "provider_type": provider_db.provider_type,
                "tenant_id": str(self.tenant.id) if self.tenant else None,
            }
        )

        return TenantModelAdapter(
            model=model,
            credential_resolver=credential_resolver,
            provider_type=provider_db.provider_type,
        )

    @staticmethod
    def is_valid_arguments(arguments: str):
        try:
            # Attempt to parse the string
            parsed = json.loads(arguments)
            # Check if the parsed object is a dictionary
            return isinstance(parsed, dict)
        except (json.JSONDecodeError, TypeError):
            # If there is a JSON decode error or TypeError, return False
            return False

    async def _handle_tool_call(self, completion: AsyncGenerator[Completion]):
        name = None
        arguments = ""
        function_called = False

        async for chunk in completion:
            # Removed per-token logging to reduce log volume in production
            # logger.debug(chunk)  # This would log 100+ times per response

            if chunk.tool_call:
                if chunk.tool_call.name:
                    name = chunk.tool_call.name

                if chunk.tool_call.arguments:
                    arguments += chunk.tool_call.arguments

                if not name or not arguments or not self.is_valid_arguments(arguments):
                    # Keep collecting the tool call
                    continue
                elif not function_called:
                    call_args = json.loads(arguments)

                    if name == "generate_image":
                        yield Completion(response_type=ResponseType.INTRIC_EVENT)

                        chunk.image_data = await generate_image(**call_args)
                        chunk.response_type = ResponseType.FILES

                        yield chunk

                    function_called = True

            elif chunk.text:
                chunk.response_type = ResponseType.TEXT

                yield chunk

    async def get_response(
        self,
        model: CompletionModel,
        text_input: str,
        model_kwargs: ModelKwargs | None = None,
        files: list[File] = [],
        prompt: str = "",
        prompt_files: list[File] = [],
        transcription_inputs: list[str] = [],
        info_blob_chunks: list[InfoBlobChunkInDBWithScore] = [],
        web_search_results: list["WebSearchResult"] = [],
        session: SessionInDB | None = None,
        stream: bool = False,
        extended_logging: bool = False,
        version: int = 1,
        use_image_generation: bool = False,
    ):
        model_adapter = await self._get_adapter(model)

        # Make sure everything fits in the context of the model
        max_tokens = model_adapter.get_token_limit_of_model()

        # Image generation only works on streaming for now
        # And only if feature flag is turned on
        use_image_generation = use_image_generation and stream and get_settings().using_image_generation

        context = self.context_builder.build_context(
            input_str=text_input,
            max_tokens=max_tokens,
            files=files,
            prompt=prompt,
            session=session,
            info_blob_chunks=info_blob_chunks,
            prompt_files=prompt_files,
            transcription_inputs=transcription_inputs,
            version=version,
            use_image_generation=use_image_generation,
            web_search_results=web_search_results,
        )

        if extended_logging:
            logging_details = model_adapter.get_logging_details(
                context=context, model_kwargs=model_kwargs
            )
        else:
            logging_details = None

        if not stream:
            completion = await model_adapter.get_response(
                context=context,
                model_kwargs=model_kwargs,
            )
        else:
            # Two-phase streaming pattern:
            # Phase 1: Create stream connection BEFORE returning (can raise exceptions)
            # This happens eagerly, so exceptions propagate before HTTP response starts
            stream_obj = await model_adapter.prepare_streaming(
                context=context,
                model_kwargs=model_kwargs,
            )

            # Phase 2: Create generator that iterates the pre-created stream
            # This generator yields error events for mid-stream failures
            async def streaming_wrapper():
                """
                Generator that iterates pre-created stream.
                The stream was already created and validated, so we're past
                the pre-flight checks. Any errors here are mid-stream failures.
                """
                async for chunk in model_adapter.iterate_stream(
                    stream=stream_obj,
                    context=context,
                    model_kwargs=model_kwargs,
                ):
                    yield chunk

            completion = self._handle_tool_call(streaming_wrapper())

        return CompletionModelResponse(
            completion=completion,
            model=model_adapter.model,
            extended_logging=logging_details,
            total_token_count=context.token_count,
        )


class CompletionServiceFactory:
    def __init__(self, container: Container):
        self.container = container
