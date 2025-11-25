from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional, Union
from uuid import UUID

from pydantic import BaseModel

from intric.ai_models.model_enums import ModelFamily as CompletionModelFamily
from intric.ai_models.model_enums import ModelHostingLocation, ModelStability
from intric.ai_models.model_enums import ModelOrg as Orgs
from intric.files.file_models import File
from intric.logging.logging import LoggingDetails
from intric.main.models import NOT_PROVIDED, InDB, ModelId, NotProvided, partial_model
from intric.security_classifications.presentation.security_classification_models import (
    SecurityClassificationPublic,
)

if TYPE_CHECKING:
    from intric.completion_models.domain.completion_model import (
        CompletionModel as CompletionModelDomain,
    )
    from intric.info_blobs.info_blob import InfoBlobChunkInDBWithScore


class ResponseType(str, Enum):
    TEXT = "text"
    INTRIC_EVENT = "intric_event"
    FILES = "image"
    FIRST_CHUNK = "first_chunk"
    ERROR = "error"


@dataclass
class FunctionDefinition:
    name: str
    description: str
    schema: dict


@dataclass
class FunctionCall:
    name: Optional[str] = None
    arguments: Optional[str] = None


@dataclass
class Completion:
    reasoning_token_count: Optional[int] = 0
    text: Optional[str] = None
    reference_chunks: Optional[list[InfoBlobChunkInDBWithScore]] = None
    tool_call: Optional[FunctionCall] = None
    image_data: Optional[bytes] = None
    response_type: Optional[ResponseType] = None
    generated_file: Optional[File] = None
    stop: bool = False
    error: Optional[str] = None
    error_code: Optional[int] = None


class CompletionModelBase(BaseModel):
    name: str
    nickname: str
    family: CompletionModelFamily
    token_limit: int
    is_deprecated: bool
    nr_billion_parameters: Optional[int] = None
    hf_link: Optional[str] = None
    stability: ModelStability
    hosting: ModelHostingLocation
    open_source: Optional[bool] = None
    description: Optional[str] = None
    deployment_name: Optional[str] = None
    org: Optional[Orgs] = None
    vision: bool
    reasoning: bool
    base_url: Optional[str] = None
    litellm_model_name: Optional[str] = None


class CompletionModelCreate(CompletionModelBase):
    pass


@partial_model
class CompletionModelUpdate(CompletionModelBase):
    id: UUID


class CompletionModelUpdateFlags(BaseModel):
    is_org_enabled: Optional[bool] = None
    is_org_default: Optional[bool] = None
    security_classification: Union[ModelId, None, NotProvided] = NOT_PROVIDED


class CompletionModel(CompletionModelBase, InDB):
    is_org_enabled: bool = False
    is_org_default: bool = False


class CompletionModelPublic(CompletionModel):
    can_access: bool = False
    is_locked: bool = True
    lock_reason: Optional[str] = None
    credential_provider: Optional[str] = None
    security_classification: Optional[SecurityClassificationPublic] = None

    @classmethod
    def from_domain(cls, completion_model: CompletionModelDomain):
        return cls(
            id=completion_model.id,
            created_at=completion_model.created_at,
            updated_at=completion_model.updated_at,
            name=completion_model.name,
            nickname=completion_model.nickname,
            family=completion_model.family,
            token_limit=completion_model.token_limit,
            is_deprecated=completion_model.is_deprecated,
            nr_billion_parameters=completion_model.nr_billion_parameters,
            hf_link=completion_model.hf_link,
            stability=completion_model.stability,
            hosting=completion_model.hosting,
            open_source=completion_model.open_source,
            description=completion_model.description,
            deployment_name=completion_model.deployment_name,
            org=completion_model.org,
            vision=completion_model.vision,
            reasoning=completion_model.reasoning,
            base_url=completion_model.base_url,
            litellm_model_name=completion_model.litellm_model_name,
            is_org_enabled=completion_model.is_org_enabled,
            is_org_default=completion_model.is_org_default,
            can_access=completion_model.can_access,
            is_locked=completion_model.is_locked,
            lock_reason=completion_model.lock_reason,
            credential_provider=completion_model.get_credential_provider_name(),
            security_classification=SecurityClassificationPublic.from_domain(
                completion_model.security_classification,
                return_none_if_not_enabled=False,
            ),
        )


class CompletionModelSecurityStatus(CompletionModelPublic):
    meets_security_classification: Optional[bool] = None


class CompletionModelResponse(BaseModel):
    completion: Union[str, Any]  # Pydantic doesn't support AsyncIterable
    model: CompletionModel
    extended_logging: Optional[LoggingDetails] = None
    total_token_count: int


class Message(BaseModel):
    question: str
    answer: str
    images: list[File] = []
    generated_images: list[File] = []


class Context(BaseModel):
    input: str
    token_count: int = 0
    prompt: str = ""
    messages: list[Message] = []
    images: list[File] = []
    function_definitions: list[FunctionDefinition] = []


class ModelKwargs(BaseModel):
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    reasoning_effort: Optional[str] = None
    verbosity: Optional[str] = None
    response_format: Optional[dict] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    top_k: Optional[int] = None


class CompletionModelSparse(CompletionModelBase, InDB):
    pass
