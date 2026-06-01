from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel
from typing_extensions import override

from intric.main.models import InDB, partial_model


class EmbeddingModelBase(BaseModel):
    name: str
    family: Optional[str] = None
    is_deprecated: bool
    open_source: bool
    dimensions: Optional[int] = None
    max_input: Optional[int] = None
    max_batch_size: Optional[int] = None
    hf_link: Optional[str] = None
    stability: Optional[str] = None
    hosting: Optional[str] = None
    description: Optional[str] = None
    org: Optional[str] = None
    litellm_model_name: Optional[str] = None
    # Indicative USD ratecard. Output is almost always 0 for embeddings but
    # kept for symmetry with completion-model pricing.
    input_cost_per_token: Optional[Decimal] = None
    output_cost_per_token: Optional[Decimal] = None

    @classmethod
    def _validate_batch_size(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return value
        if value < 1:
            raise ValueError("max_batch_size must be greater than 0")
        if value > 256:
            raise ValueError("max_batch_size must not exceed 256")
        return value

    @override
    def model_post_init(self, __context: Any) -> None:
        super().model_post_init(__context)
        # Pydantic v2 hook to validate custom constraints
        self.max_batch_size = self._validate_batch_size(self.max_batch_size)


class EmbeddingModelCreate(EmbeddingModelBase):
    pass


@partial_model
class EmbeddingModelUpdate(EmbeddingModelBase):
    id: UUID


class EmbeddingModelUpdateFlags(BaseModel):
    is_org_enabled: Optional[bool] = False


class EmbeddingModelLegacy(EmbeddingModelBase, InDB):
    is_org_enabled: bool = False


class EmbeddingModelPublicBase(EmbeddingModelBase, InDB):
    pass


class EmbeddingModelPublicLegacy(EmbeddingModelLegacy):
    can_access: bool = False
    is_locked: bool = True
    lock_reason: Optional[str] = None


class EmbeddingModelSparse(EmbeddingModelBase, InDB):
    pass
