from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from intric.ai_models.completion_models.completion_model import (
        CompletionModel,
        Context,
        ModelKwargs,
    )
    from intric.logging.logging import LoggingDetails


class CompletionModelAdapter(ABC):
    def __init__(self, model: "CompletionModel"):
        self.model = model

    def get_token_limit_of_model(self):
        raise NotImplementedError()

    def get_logging_details(
        self, context: "Context", model_kwargs: "ModelKwargs"
    ) -> "LoggingDetails":
        raise NotImplementedError()

    async def get_response(
        self, context: "Context", model_kwargs: "ModelKwargs", mcp_proxy=None, **kwargs
    ):
        raise NotImplementedError()

    def get_response_streaming(self, context: "Context", model_kwargs: "ModelKwargs"):
        """
        Legacy streaming method for backward compatibility.

        New implementations should use the two-phase pattern:
        1. prepare_streaming() - creates stream connection (can raise exceptions)
        2. iterate_stream() - iterates the stream (yields error events for failures)

        Default implementation uses the two-phase pattern internally.
        """
        raise NotImplementedError()

    @abstractmethod
    async def prepare_streaming(
        self,
        context: "Context",
        model_kwargs: "ModelKwargs | None" = None,
        mcp_proxy=None,
        **kwargs,
    ) -> Any:
        """
        Phase 1 (Pre-flight): Create streaming connection BEFORE EventSourceResponse.

        This method creates and validates the stream connection before any HTTP response
        is sent. Exceptions raised here will properly propagate as HTTP error responses.

        Can raise:
            - HTTPException: For proper HTTP error responses
            - APIKeyNotConfiguredException: Missing or invalid credentials
            - OpenAIException: Provider-specific errors (firewall, rate limit, etc.)
            - BadRequestException: Invalid parameters

        Args:
            context: The conversation context
            model_kwargs: Optional model parameters

        Returns:
            Stream object ready for iteration (provider-specific type)
        """
        pass

    @abstractmethod
    async def iterate_stream(
        self,
        stream: Any,
        context: "Context" = None,
        model_kwargs: "ModelKwargs | None" = None,
        require_tool_approval: bool = False,
        approval_manager=None,
    ):
        """
        Phase 2 (Iteration): Iterate pre-created stream INSIDE EventSourceResponse.

        This async generator yields Completion objects from a stream that was already
        created and validated by prepare_streaming(). Called AFTER HTTP 200 is sent.

        For mid-stream failures (connection drops, etc.), this should yield error events
        instead of raising exceptions, since the HTTP response has already started.

        Example error event:
            yield Completion(
                text="",
                error="Stream error: Connection lost",
                error_code=500,
                response_type=ResponseType.ERROR,
                stop=True
            )

        Args:
            stream: The stream object from prepare_streaming()
            context: Optional conversation context (for logging)
            model_kwargs: Optional model parameters (for logging)

        Yields:
            Completion: Completion objects with text chunks or error events
        """
        pass
