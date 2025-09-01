from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional, Union
from uuid import UUID

from pydantic import BaseModel, field_validator

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
    
    # Default model parameters (stored as JSONB for flexibility)
    default_settings: Optional[dict] = None
    
    # Convenience properties for accessing default settings
    @property
    def default_temperature(self) -> Optional[float]:
        return self.default_settings.get('temperature') if self.default_settings else None
    
    @property 
    def default_top_p(self) -> Optional[float]:
        return self.default_settings.get('top_p') if self.default_settings else None
        
    @property
    def default_reasoning_effort(self) -> Optional[str]:
        return self.default_settings.get('reasoning_effort') if self.default_settings else None
        
    @property
    def default_verbosity(self) -> Optional[str]:
        return self.default_settings.get('verbosity') if self.default_settings else None
        
    @property
    def default_max_completion_tokens(self) -> Optional[int]:
        return self.default_settings.get('max_completion_tokens') if self.default_settings else None
        
    @property
    def default_max_reasoning_tokens(self) -> Optional[int]:
        return self.default_settings.get('max_reasoning_tokens') if self.default_settings else None
        
    @property
    def default_max_thinking_tokens(self) -> Optional[int]:
        return self.default_settings.get('max_thinking_tokens') if self.default_settings else None


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
    security_classification: Optional[SecurityClassificationPublic] = None
    supports_verbosity: bool = False

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
            default_settings=completion_model.default_settings,
            is_org_enabled=completion_model.is_org_enabled,
            is_org_default=completion_model.is_org_default,
            can_access=completion_model.can_access,
            is_locked=completion_model.is_locked,
            security_classification=SecurityClassificationPublic.from_domain(
                completion_model.security_classification,
                return_none_if_not_enabled=False,
            ),
            supports_verbosity=completion_model.supports_verbosity(),
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
    # Basic parameters
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    
    # Reasoning parameters
    reasoning_effort: Optional[str] = None  # "minimal", "low", "medium", "high" (OpenAI o1/o3/GPT-5)
    max_reasoning_tokens: Optional[int] = None  # OpenAI o1/o3
    max_thinking_tokens: Optional[int] = None  # Claude 3.5 Sonnet/Haiku
    
    # GPT-5 specific parameters
    verbosity: Optional[str] = None  # "low", "medium", "high"
    
    # General parameters
    max_completion_tokens: Optional[int] = None
    max_tokens: Optional[int] = None
    
    @field_validator('temperature')
    @classmethod
    def validate_temperature(cls, v):
        if v is not None and (v < 0 or v > 2):
            raise ValueError('temperature must be between 0 and 2')
        return v
    
    @field_validator('top_p')
    @classmethod
    def validate_top_p(cls, v):
        if v is not None and (v < 0 or v > 1):
            raise ValueError('top_p must be between 0 and 1')
        return v
    
    @field_validator('reasoning_effort')
    @classmethod
    def validate_reasoning_effort(cls, v):
        if v is not None and v not in ["minimal", "low", "medium", "high"]:
            raise ValueError('reasoning_effort must be one of: minimal, low, medium, high')
        return v
    
    @field_validator('verbosity')
    @classmethod
    def validate_verbosity(cls, v):
        if v is not None and v not in ["low", "medium", "high"]:
            raise ValueError('verbosity must be one of: low, medium, high')
        return v
    
    @field_validator('max_reasoning_tokens', 'max_thinking_tokens', 'max_completion_tokens', 'max_tokens')
    @classmethod
    def validate_token_limits(cls, v):
        if v is not None and v < 1:
            raise ValueError('token limits must be positive integers')
        return v


class CompletionModelSparse(CompletionModelBase, InDB):
    pass
