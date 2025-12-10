from typing import TYPE_CHECKING, Optional

from intric.embedding_models.infrastructure.adapters.base import EmbeddingModelAdapter
from intric.embedding_models.infrastructure.adapters.litellm_embeddings import (
    LiteLLMEmbeddingAdapter,
)
from intric.files.chunk_embedding_list import ChunkEmbeddingList
from intric.info_blobs.info_blob import InfoBlobChunk
from intric.main.config import SETTINGS, Settings
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.database.database import AsyncSession
    from intric.embedding_models.domain.embedding_model import EmbeddingModel
    from intric.settings.encryption_service import EncryptionService
    from intric.tenants.tenant import TenantInDB

logger = get_logger(__name__)


class CreateEmbeddingsService:
    def __init__(
        self,
        tenant: Optional["TenantInDB"] = None,
        config: Optional[Settings] = None,
        encryption_service: Optional["EncryptionService"] = None,
        session: Optional["AsyncSession"] = None,
    ):
        self.tenant = tenant
        self.config = config or SETTINGS
        self.encryption_service = encryption_service
        self.session = session

    async def _get_adapter(self, model: "EmbeddingModel") -> EmbeddingModelAdapter:
        """
        Get the adapter for the given embedding model.

        All models must have a provider_id linking to a ModelProvider.
        Uses LiteLLMEmbeddingAdapter which routes through LiteLLM.
        """
        import sqlalchemy as sa
        from intric.database.tables.model_providers_table import ModelProviders
        from intric.model_providers.infrastructure.tenant_model_credential_resolver import (
            TenantModelCredentialResolver,
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
                "Please ensure the CreateEmbeddingsService is initialized with a database session."
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

        # Construct LiteLLM model name with provider prefix
        litellm_model_name = f"{provider_db.provider_type}/{model.name}"

        # Temporarily set litellm_model_name on the model for the adapter
        # (the model object is not persisted, so this is safe)
        model.litellm_model_name = litellm_model_name

        logger.info(
            f"Using LiteLLMEmbeddingAdapter for model '{model.name}'",
            extra={
                "model_id": str(model.id) if hasattr(model, 'id') else None,
                "model_name": model.name,
                "provider_id": str(model.provider_id),
                "provider_type": provider_db.provider_type,
                "litellm_model_name": litellm_model_name,
                "tenant_id": str(self.tenant.id) if self.tenant else None,
            }
        )

        return LiteLLMEmbeddingAdapter(
            model, credential_resolver=credential_resolver
        )

    async def get_embeddings(
        self,
        model: "EmbeddingModel",
        chunks: list[InfoBlobChunk],
    ) -> ChunkEmbeddingList:
        adapter = await self._get_adapter(model)
        return await adapter.get_embeddings(chunks)

    async def get_embedding_for_query(
        self,
        model: "EmbeddingModel",
        query: str,
    ) -> list[float]:
        adapter = await self._get_adapter(model)
        return await adapter.get_embedding_for_query(query)
