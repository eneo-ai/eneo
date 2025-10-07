from typing import TYPE_CHECKING, Optional

from intric.ai_models.model_enums import ModelFamily
from intric.embedding_models.infrastructure.adapters.base import EmbeddingModelAdapter
from intric.embedding_models.infrastructure.adapters.e5_embeddings import E5Adapter
from intric.embedding_models.infrastructure.adapters.litellm_embeddings import (
    LiteLLMEmbeddingAdapter,
)
from intric.embedding_models.infrastructure.adapters.openai_embeddings import (
    OpenAIEmbeddingAdapter,
)
from intric.files.chunk_embedding_list import ChunkEmbeddingList
from intric.info_blobs.info_blob import InfoBlobChunk
from intric.main.config import SETTINGS, Settings
from intric.settings.credential_resolver import CredentialResolver

if TYPE_CHECKING:
    from intric.embedding_models.domain.embedding_model import EmbeddingModel
    from intric.settings.encryption_service import EncryptionService
    from intric.tenants.tenant import TenantInDB


class CreateEmbeddingsService:
    def __init__(
        self,
        tenant: Optional["TenantInDB"] = None,
        config: Optional[Settings] = None,
        encryption_service: Optional["EncryptionService"] = None,
    ):
        self._adapters = {
            ModelFamily.OPEN_AI: OpenAIEmbeddingAdapter,
            ModelFamily.E5: E5Adapter,
        }
        self.tenant = tenant
        self.config = config or SETTINGS
        self.encryption_service = encryption_service

    def _get_adapter(self, model: "EmbeddingModel") -> EmbeddingModelAdapter:
        # Create credential resolver with tenant context if tenant is available
        credential_resolver = None
        if self.tenant:
            credential_resolver = CredentialResolver(
                tenant=self.tenant,
                settings=self.config,
                encryption_service=self.encryption_service,
            )

        # Check for LiteLLM model first
        if model.litellm_model_name:
            return LiteLLMEmbeddingAdapter(
                model, credential_resolver=credential_resolver
            )

        # Fall back to existing family-based selection
        adapter_class = self._adapters.get(model.family.value)
        if not adapter_class:
            raise ValueError(f"No adapter found for hosting {model.family.value}")

        return adapter_class(model, credential_resolver=credential_resolver)

    async def get_embeddings(
        self,
        model: "EmbeddingModel",
        chunks: list[InfoBlobChunk],
    ) -> ChunkEmbeddingList:
        adapter = self._get_adapter(model)
        return await adapter.get_embeddings(chunks)

    async def get_embedding_for_query(
        self,
        model: "EmbeddingModel",
        query: str,
    ) -> list[float]:
        adapter = self._get_adapter(model)
        return await adapter.get_embedding_for_query(query)
