from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SemanticSearchRequest(BaseModel):
    search_string: str
    num_chunks: int = 30
    autocut_cutoff: Optional[int] = Field(
        description="Experimental feature that tries to limit the amount "
        "of chunks to only the relevant ones, based on the score. "
        "Set to null (or omit completely) to not use this feature",
        default=None,
    )
    rerank: bool = Field(
        default=False,
        description="Rerank the candidates with the installation's default rerank "
        "model. Reranked results carry the reranker's scores and autocut_cutoff "
        "is ignored; without a usable rerank model the search runs as without "
        "this flag.",
    )


class SemanticSearchResponse(BaseModel):
    id: UUID
    info_blob_id: UUID
    text: str
    score: float
    created_at: datetime
    updated_at: datetime
