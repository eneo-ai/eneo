from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from intric.ai_models.completion_models.completion_model import (
    ModelHostingLocation,
    ModelStability,
    Orgs,
)
from intric.main.models import InDB, partial_model


class EmbeddingModelFamily(str, Enum):
    OPEN_AI = "openai"
    MINI_LM = "mini_lm"
    E5 = "e5"


class EmbeddingModelBase(BaseModel):
    name: str
    family: EmbeddingModelFamily
    is_deprecated: bool
    open_source: bool
    dimensions: Optional[int] = None
    max_input: Optional[int] = None
    max_batch_size: Optional[int] = None
    hf_link: Optional[str] = None
    stability: ModelStability
    hosting: ModelHostingLocation
    description: Optional[str] = None
    org: Optional[Orgs] = None
    litellm_model_name: Optional[str] = None

    @classmethod
    def _validate_batch_size(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return value
        if value < 1:
            raise ValueError("max_batch_size must be greater than 0")
        if value > 256:
            raise ValueError("max_batch_size must not exceed 256")
        return value

    def model_post_init(self, __context):
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


class EmbeddingModelSparse(EmbeddingModelBase, InDB):
    pass
