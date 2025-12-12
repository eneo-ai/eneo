"""
CrawlContext DTO for Hybrid v2 session-per-batch pattern.

This dataclass holds all context needed during a crawl operation as primitives.
NO ORM objects - prevents DetachedInstanceError when sessions close between batches.

The frozen=True ensures immutability during the crawl lifecycle.
"""

from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class CrawlContext:
    """
    Immutable context for crawl operations - ALL fields are primitives.

    This DTO extracts all required data from ORM objects at crawl start,
    allowing sessions to be closed during network I/O without causing
    DetachedInstanceError.

    Used by:
    - persist_batch() for page persistence
    - crawl loop for settings access
    - heartbeat for TTL refresh
    """

    # Core identifiers
    website_id: UUID
    tenant_id: UUID
    tenant_slug: str | None
    user_id: UUID

    # Embedding model - extract ALL fields to avoid lazy-load
    embedding_model_id: UUID | None
    embedding_model_name: str | None
    embedding_model_open_source: bool
    embedding_model_family: str | None  # EmbeddingModelFamily enum value as string
    embedding_model_dimensions: int | None

    # HTTP Auth - primitives only (extracted from HttpAuthCredentials)
    # SECURITY: repr=False prevents password exposure in logs/tracebacks
    http_auth_user: str | None = field(default=None)
    http_auth_pass: str | None = field(default=None, repr=False)

    # Batch settings - control memory and flush behavior
    # batch_size: max pages per batch (default conservative per multi-model consensus)
    batch_size: int = 50
    # max_batch_content_bytes: 10MB cap on raw content per batch
    max_batch_content_bytes: int = 10_000_000
    # max_batch_embedding_bytes: 50MB cap on prepared embeddings per batch
    # Embedding math: 1536 dims × 4 bytes × ~20 chunks/page × 50 pages ≈ 6MB typical
    max_batch_embedding_bytes: int = 50_000_000

    # Timeout settings - fail-fast guards
    # embedding_timeout_seconds: max time per embedding API call (GPT-5.2/Gemini consensus: 15-20s)
    embedding_timeout_seconds: int = 15
    # max_transaction_wall_time_seconds: hard ceiling on Phase 2 persist (consensus: 30s)
    max_transaction_wall_time_seconds: int = 30


@dataclass
class PreparedPage:
    """
    Page data prepared in Phase 1 for persistence in Phase 2.

    Contains pre-computed embeddings and content hash, ready for DB write.
    All fields are primitives - no ORM dependencies.

    Phase 1 (Pure Compute):
    - Chunk text locally
    - Compute content hash
    - Call embedding API (outside DB session)
    - Create PreparedPage with results

    Phase 2 (Short-lived Session):
    - Use PreparedPage data for bulk insert
    - Delete-then-insert for deduplication
    - Commit with per-page savepoints
    """

    # Page identification
    url: str
    title: str

    # Content data
    content: str
    content_hash: bytes  # SHA-256 for change detection (future deduplication)

    # Pre-computed embeddings (Phase 1 result)
    chunks: list[str]  # Text chunks
    embeddings: list[list[float]]  # Embedding vectors per chunk

    # Context for persistence
    tenant_id: UUID
    website_id: UUID
    user_id: UUID
    embedding_model_id: UUID
