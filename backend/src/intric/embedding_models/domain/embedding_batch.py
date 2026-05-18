from dataclasses import dataclass
from typing import Literal

from intric.files.chunk_embedding_list import ChunkEmbeddingList

EmbeddingUsageSource = Literal["provider_reported", "missing"]


@dataclass(frozen=True, slots=True)
class EmbeddingUsage:
    prompt_tokens: int | None
    total_tokens: int | None
    source: EmbeddingUsageSource


@dataclass(frozen=True, slots=True)
class EmbeddingBatchResult:
    embeddings: ChunkEmbeddingList
    usage: EmbeddingUsage
