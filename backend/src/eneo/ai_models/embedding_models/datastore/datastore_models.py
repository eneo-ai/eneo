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


class SemanticSearchResponse(BaseModel):
    id: UUID
    info_blob_id: UUID
    text: str
    score: float
    created_at: datetime
    updated_at: datetime
