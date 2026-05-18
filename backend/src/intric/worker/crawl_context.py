"""Primitive crawl DTOs used after bootstrap has released the database session."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from intric.embedding_models.domain.embedding_batch import EmbeddingUsage


@dataclass(frozen=True)
class EmbeddingModelSpec:
    """Embedding adapter inputs that must survive closed ORM sessions."""

    id: UUID
    name: str
    litellm_model_name: str | None
    family: str | None
    max_input: int
    max_batch_size: int | None  # Adapters default to 32 if None
    dimensions: int | None
    open_source: bool = False
    input_cost_per_token: Decimal | None = None
    provider_id: UUID | None = None
    provider_type: str | None = None
    provider_credentials: dict[str, Any] | None = None
    provider_config: dict[str, Any] | None = None


@dataclass(frozen=True)
class CrawlContext:
    """Frozen crawl inputs shared by network, embedding, and DB phases."""

    website_id: UUID
    tenant_id: UUID
    tenant_slug: str | None
    user_id: UUID

    embedding_model_id: UUID | None
    embedding_model_name: str | None
    embedding_model_open_source: bool
    embedding_model_family: str | None
    embedding_model_dimensions: int | None

    http_auth_user: str | None = field(default=None)
    http_auth_pass: str | None = field(default=None, repr=False)

    batch_size: int = 50
    max_batch_content_bytes: int = 10_000_000
    max_batch_embedding_bytes: int = 50_000_000

    # Keep embedding calls short so a slow provider does not hold the crawler batch open.
    embedding_timeout_seconds: int = 15
    # The database phase should stay bounded because it holds a pooled connection.
    max_transaction_wall_time_seconds: int = 30
    run_id: UUID = field(default_factory=uuid4)


@dataclass
class PreparedPage:
    """Prepared page payload passed from network/embedding work into DB writes."""

    url: str
    title: str

    content: str
    content_hash: bytes

    chunks: list[str]
    embeddings: list[list[float]]
    embedding_usage: EmbeddingUsage

    tenant_id: UUID
    website_id: UUID
    user_id: UUID
    embedding_model_id: UUID
