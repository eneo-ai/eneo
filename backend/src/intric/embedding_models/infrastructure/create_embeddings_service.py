from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional, Protocol, TypeGuard, runtime_checkable
from uuid import UUID

from intric.embedding_models.domain.embedding_batch import EmbeddingBatchResult
from intric.embedding_models.infrastructure.adapters.base import EmbeddingModelAdapter
from intric.embedding_models.infrastructure.adapters.litellm_embeddings import (
    LiteLLMEmbeddingAdapter,
)
from intric.info_blobs.info_blob import InfoBlobChunk
from intric.main.config import SETTINGS, Settings
from intric.main.exceptions import ProviderInactiveException, ProviderNotFoundException
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.database.database import AsyncSession
    from intric.settings.encryption_service import EncryptionService
    from intric.tenants.tenant import TenantInDB

logger = get_logger(__name__)


class EmbeddingModelLike(Protocol):
    """Protocol defining the interface for embedding model objects.

    This allows both ORM EmbeddingModel and frozen EmbeddingModelSpec DTO
    to be used interchangeably via duck typing. The adapters only access
    these attributes, so any object providing them will work.
    """

    @property
    def id(self) -> UUID: ...

    @property
    def name(self) -> str: ...

    @property
    def provider_id(self) -> UUID | None: ...

    @property
    def litellm_model_name(self) -> str | None: ...

    @property
    def family(self) -> str | None: ...

    @property
    def max_input(self) -> int | None: ...

    @property
    def max_batch_size(self) -> int | None: ...

    @property
    def dimensions(self) -> int | None: ...

    @property
    def open_source(self) -> bool: ...

    @property
    def input_cost_per_token(self) -> Decimal | None: ...


@runtime_checkable
class _PotentialPreResolvedEmbeddingModelLike(EmbeddingModelLike, Protocol):
    @property
    def provider_type(self) -> str | None: ...

    @property
    def provider_credentials(self) -> dict[str, Any] | None: ...

    @property
    def provider_config(self) -> dict[str, Any] | None: ...


class PreResolvedEmbeddingModelLike(EmbeddingModelLike, Protocol):
    """Embedding model whose provider data is already loaded."""

    @property
    def provider_type(self) -> str: ...

    @property
    def provider_credentials(self) -> dict[str, Any]: ...

    @property
    def provider_config(self) -> dict[str, Any] | None: ...


def is_pre_resolved(model: object) -> TypeGuard[PreResolvedEmbeddingModelLike]:
    """Return true when an embedding model can build an adapter without DB lookup."""

    if not isinstance(model, _PotentialPreResolvedEmbeddingModelLike):
        return False

    return bool(model.provider_type) and model.provider_credentials is not None


class CreateEmbeddingsService:
    def __init__(
        self,
        tenant: Optional["TenantInDB"] = None,
        config: Optional[Settings] = None,
        encryption_service: Optional["EncryptionService"] = None,
        session: Optional["AsyncSession"] = None,
    ) -> None:
        super().__init__()
        self.tenant = tenant
        self.config = config or SETTINGS
        self.encryption_service = encryption_service
        self.session = session

    async def _get_adapter(self, model: EmbeddingModelLike) -> EmbeddingModelAdapter:
        """Get the appropriate adapter for the embedding model.

        All models must have a provider_id linking to a ModelProvider.
        Uses LiteLLMEmbeddingAdapter which routes through LiteLLM.

        Supports two paths for provider resolution:
        1. Pre-resolved: If model carries provider_type/provider_credentials
           (e.g. EmbeddingModelSpec from crawl bootstrap), skip DB lookup.
        2. DB lookup: Load provider from database using provider_id + session.
        """
        from intric.model_providers.infrastructure.tenant_model_credential_resolver import (
            TenantModelCredentialResolver,
        )

        if not model.provider_id:
            raise ValueError(
                f"Model '{model.name}' is missing required provider_id. "
                "All models must be associated with a ModelProvider."
            )

        if is_pre_resolved(model):
            # Pre-resolved path: no DB session needed
            if self.encryption_service is None:
                raise ValueError(
                    "CreateEmbeddingsService requires an encryption_service to resolve credentials."
                )
            credential_resolver = TenantModelCredentialResolver(
                provider_id=model.provider_id,
                provider_type=model.provider_type,
                credentials=model.provider_credentials,
                config=model.provider_config or {},
                encryption_service=self.encryption_service,
            )
            litellm_model_name = f"{model.provider_type}/{model.name}"
            provider_type = model.provider_type
        else:
            # DB lookup path: requires active session
            import sqlalchemy as sa

            from intric.database.tables.model_providers_table import ModelProviders

            if not self.session:
                logger.error(
                    "Model requires database session but none available",
                    extra={
                        "model_id": str(model.id),
                        "model_name": model.name,
                        "provider_id": str(model.provider_id),
                        "tenant_id": str(self.tenant.id) if self.tenant else None,
                    },
                )
                raise ValueError(
                    f"Model '{model.name}' requires database session to load provider credentials. "
                    "Please ensure the CreateEmbeddingsService is initialized with a database session."
                )

            stmt = sa.select(ModelProviders).where(
                ModelProviders.id == model.provider_id
            )
            result = await self.session.execute(stmt)
            provider_db = result.scalar_one_or_none()

            if provider_db is None:
                raise ProviderNotFoundException(
                    f"Model provider '{model.provider_id}' not found. "
                    "The provider may have been deleted or is not accessible."
                )

            if not provider_db.is_active:
                raise ProviderInactiveException(
                    f"The model provider '{provider_db.name}' is currently inactive. "
                    "Please contact your administrator to enable the provider."
                )

            if self.encryption_service is None:
                raise ValueError(
                    "CreateEmbeddingsService requires an encryption_service to resolve credentials."
                )
            credential_resolver = TenantModelCredentialResolver(
                provider_id=provider_db.id,
                provider_type=provider_db.provider_type,
                credentials=provider_db.credentials,
                config=provider_db.config,
                encryption_service=self.encryption_service,
            )
            litellm_model_name = f"{provider_db.provider_type}/{model.name}"
            provider_type = provider_db.provider_type

        logger.info(
            f"Using LiteLLMEmbeddingAdapter for model '{model.name}'",
            extra={
                "model_id": str(model.id),
                "model_name": model.name,
                "provider_id": str(model.provider_id),
                "provider_type": provider_type,
                "litellm_model_name": litellm_model_name,
                "tenant_id": str(self.tenant.id) if self.tenant else None,
            },
        )

        return LiteLLMEmbeddingAdapter(
            model,
            credential_resolver=credential_resolver,
            litellm_model_name=litellm_model_name,
        )

    async def get_embeddings(
        self,
        model: EmbeddingModelLike,
        chunks: list[InfoBlobChunk],
    ) -> EmbeddingBatchResult:
        """Generate embeddings for text chunks."""
        adapter = await self._get_adapter(model)
        return await adapter.get_embeddings(chunks)

    async def get_embedding_for_query(
        self,
        model: EmbeddingModelLike,
        query: str,
    ) -> list[float]:
        """Generate embedding for a search query."""
        adapter = await self._get_adapter(model)
        return await adapter.get_embedding_for_query(query)
