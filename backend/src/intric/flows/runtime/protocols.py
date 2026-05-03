"""Structural Protocols consumed by the flow runtime layer.

These Protocols document the exact surface the runtime needs from the
`Assistant` aggregate without creating a hard dependency on it. They live
in this leaf-most module so consumers — `step_execution_runtime`,
`rag_retrieval`, `executor` — can pull the contract without dragging the
producer's transitive import graph.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from intric.ai_models.completion_models.completion_model import (
    CompletionModelResponse,
    ModelKwargs,
)
from intric.completion_models.infrastructure.completion_service import CompletionService
from intric.files.file_models import File
from intric.info_blobs.info_blob import InfoBlobChunkInDBWithScore
from intric.sessions.session import SessionInDB

if TYPE_CHECKING:
    from intric.collections.domain.collection import Collection
    from intric.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from intric.websites.domain.website import Website


class RuntimeCompletionModelProtocol(Protocol):
    """Subset of CompletionModel attributes consumed by the flow runtime.

    Defined as a Protocol (rather than importing the concrete domain class)
    so unit tests can use lightweight fakes and so the runtime layer
    documents exactly which CompletionModel fields it depends on.
    """

    id: UUID
    name: str
    provider_type: str | None
    litellm_model_name: str | None


class RuntimeAssistantProtocol(Protocol):
    """Surface of `Assistant` consumed by flow runtime modules.

    `get_response` mirrors the concrete `Assistant.get_response` signature
    in full because Pyright's structural compatibility check is positional
    for positional-or-keyword parameters: dropping a parameter shifts later
    positions and breaks compatibility (e.g. dropping `extended_logging`
    moves `prompt_override` into the position where the concrete declares
    `prompt`, producing "Parameter name mismatch"). The runtime only calls
    a subset of these arguments by keyword.
    """

    @property
    def completion_model(self) -> RuntimeCompletionModelProtocol | None: ...
    @property
    def completion_model_kwargs(self) -> ModelKwargs: ...
    @property
    def collections(self) -> list[Collection]: ...
    @property
    def websites(self) -> list[Website]: ...
    @property
    def integration_knowledge_list(self) -> list[IntegrationKnowledge]: ...

    def has_knowledge(self) -> bool: ...
    def get_prompt_text(self) -> str: ...

    async def get_response(
        self,
        question: str,
        completion_service: CompletionService,
        model_kwargs: ModelKwargs | None = None,
        files: list[File] | None = None,
        info_blob_chunks: list[InfoBlobChunkInDBWithScore] | None = None,
        session: SessionInDB | None = None,
        stream: bool = False,
        extended_logging: bool = False,
        prompt_override: str | None = None,
        prompt: str | None = None,
        version: int = 1,
    ) -> CompletionModelResponse: ...
