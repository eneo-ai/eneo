from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional, Union, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, computed_field, model_validator

from intric.completion_models.domain.model_kwargs_capabilities import (
    SupportedModelKwargs,
    coerce_model_kwargs_capabilities,
    resolve_supported_model_kwargs,
)
from intric.files.file_models import File
from intric.logging.logging import LoggingDetails
from intric.main.models import NOT_PROVIDED, InDB, ModelId, NotProvided, partial_model
from intric.model_providers.domain.model_defaults import lookup_model_defaults
from intric.security_classifications.presentation.security_classification_models import (
    SecurityClassificationPublic,
)

if TYPE_CHECKING:
    from intric.completion_models.domain.completion_model import (
        CompletionModel as CompletionModelDomain,
    )
    from intric.info_blobs.info_blob import InfoBlobChunkInDBWithScore


_COMPLETION_MODEL_FIELDS = (
    "id",
    "created_at",
    "updated_at",
    "name",
    "nickname",
    "family",
    "max_input_tokens",
    "max_output_tokens",
    "is_deprecated",
    "nr_billion_parameters",
    "hf_link",
    "stability",
    "hosting",
    "open_source",
    "description",
    "deployment_name",
    "org",
    "vision",
    "reasoning",
    "supports_tool_calling",
    "base_url",
    "litellm_model_name",
    "model_kwargs_capabilities",
    "provider_type",
    "tenant_id",
)


class TokenUsage(BaseModel):
    """Actual token usage as reported by the LLM provider."""

    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None


class ResponseType(str, Enum):
    TEXT = "text"
    INTRIC_EVENT = "intric_event"
    TOOL_CALL = "tool_call"
    TOOL_APPROVAL_REQUIRED = "tool_approval_required"
    TOOL_APPROVAL_TIMEOUT = "tool_approval_timeout"
    FILES = "image"
    FIRST_CHUNK = "first_chunk"
    TOKEN_USAGE = "token_usage"
    ERROR = "error"


@dataclass
class FunctionDefinition:
    name: str
    description: str
    schema: dict[str, object]


@dataclass
class FunctionCall:
    name: Optional[str] = None
    arguments: Optional[str] = None


@dataclass
class ToolCallMetadata:
    """Metadata for MCP tool calls to be rendered by frontend."""

    server_name: str
    tool_name: str
    arguments: Optional[dict[str, object]] = (
        None  # The input values provided to the tool
    )
    tool_call_id: Optional[str] = None  # The tool call ID for approval flow
    approved: Optional[bool] = None  # True=approved, False=denied, None=pending/auto
    # Additive state field for richer clients; legacy `approved` remains authoritative.
    result_status: Optional[str] = None
    # Text extraction of the MCP tool result. Populated once the tool has executed
    # so it can be persisted on the Question and replayed to the LLM on later turns.
    result: Optional[str] = None
    # The prefixed tool identifier the LLM sees when calling (e.g.
    # `server__tool`). `tool_name` / `server_name` above are the split/display
    # forms used by the UI; this field preserves the exact identifier needed
    # to replay the tool_use so it matches the currently-registered tools.
    mcp_tool_name: Optional[str] = None


@dataclass
class Completion:
    reasoning_token_count: Optional[int] = 0
    text: Optional[str] = None
    reference_chunks: Optional[list[InfoBlobChunkInDBWithScore]] = None
    tool_call: Optional[FunctionCall] = None
    tool_calls_metadata: Optional[list[ToolCallMetadata]] = None  # For TOOL_CALL events
    provider_response_id: Optional[str] = None
    approval_id: Optional[str] = None  # For TOOL_APPROVAL_REQUIRED events
    image_data: Optional[bytes] = None
    response_type: Optional[ResponseType] = None
    generated_file: Optional[File] = None
    stop: bool = False
    error: Optional[str] = None
    error_code: Optional[int] = None
    usage: Optional[TokenUsage] = None


def _normalize_token_fields(value: Any) -> Any:
    data: dict[str, Any]

    if isinstance(value, dict):
        data = dict(cast(dict[str, Any], value))
        token_limit = data.get("token_limit")
    else:
        missing = object()
        data = {}
        for field in _COMPLETION_MODEL_FIELDS:
            attr = getattr(value, field, missing)
            if attr is not missing:
                data[field] = attr
        data["_stored_model_projection"] = True
        token_limit = getattr(value, "token_limit", None)

    if data.get("max_input_tokens") is None and token_limit is not None:
        data["max_input_tokens"] = token_limit

    if data.get("max_output_tokens") is None:
        defaults = lookup_model_defaults(
            data.get("litellm_model_name"),
            data.get("name"),
        )
        if defaults is not None and defaults.max_output_tokens is not None:
            data["max_output_tokens"] = defaults.max_output_tokens
        elif token_limit is not None:
            data["max_output_tokens"] = token_limit

    return data


class CompletionModelBase(BaseModel):
    name: str
    nickname: Optional[str] = None
    family: Optional[str] = None
    max_input_tokens: int
    max_output_tokens: int
    is_deprecated: bool
    nr_billion_parameters: Optional[int] = None
    hf_link: Optional[str] = None
    stability: Optional[str] = None
    hosting: Optional[str] = None
    open_source: Optional[bool] = None
    description: Optional[str] = None
    deployment_name: Optional[str] = None
    org: Optional[str] = None
    vision: bool
    reasoning: bool
    supports_tool_calling: bool = False
    base_url: Optional[str] = None
    litellm_model_name: Optional[str] = None
    model_kwargs_capabilities: Optional[SupportedModelKwargs] = None

    @model_validator(mode="before")
    @classmethod
    def ignore_invalid_stored_model_kwargs_capabilities(cls, data: object) -> object:
        if isinstance(data, dict):
            values = cast(dict[str, object], data)
            if not values.get("_stored_model_projection"):
                return values
            raw_capabilities = values.get("model_kwargs_capabilities")
            completion_model_id = values.get("id")
            tenant_id = values.get("tenant_id")
        else:
            raw_capabilities = getattr(data, "model_kwargs_capabilities", None)
            completion_model_id = getattr(data, "id", None)
            tenant_id = getattr(data, "tenant_id", None)

        if raw_capabilities is None:
            return data

        capabilities = coerce_model_kwargs_capabilities(
            raw_capabilities,
            completion_model_id=completion_model_id
            if isinstance(completion_model_id, UUID)
            else None,
            tenant_id=tenant_id if isinstance(tenant_id, UUID) else None,
        )
        if capabilities is not None:
            return data

        if isinstance(data, dict):
            return {**values, "model_kwargs_capabilities": None}

        values: dict[str, object] = {}
        for field_name in cls.model_fields:
            if hasattr(data, field_name):
                values[field_name] = getattr(data, field_name)
        values["model_kwargs_capabilities"] = None
        return values

    @model_validator(mode="before")
    @classmethod
    def _normalize_fields(cls, value: Any) -> Any:
        return _normalize_token_fields(value)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def token_limit(self) -> int:
        """Backward-compat: exposed in JSON responses for frontend."""
        return self.max_input_tokens

    @computed_field  # type: ignore[prop-decorator]
    @property
    def supported_model_kwargs(self) -> SupportedModelKwargs:
        return resolve_supported_model_kwargs(
            model_kwargs_capabilities=self.model_kwargs_capabilities,
            reasoning=self.reasoning,
            provider_type=self._provider_type(),
            litellm_model_name=self.litellm_model_name,
            completion_model_id=getattr(self, "id", None),
            tenant_id=getattr(self, "tenant_id", None),
        )

    def _provider_type(self) -> str | None:
        # Keep provider_type out of create/update schemas; response projections
        # that know the provider override this method.
        return None


class CompletionModelCreate(CompletionModelBase):
    @model_validator(mode="before")
    @classmethod
    def _apply_litellm_defaults(cls, value: Any) -> Any:
        data = _normalize_token_fields(value)
        defaults = lookup_model_defaults(
            data.get("litellm_model_name"),
            data.get("name"),
        )
        if defaults is None:
            return data

        if (
            data.get("max_input_tokens") is None
            and defaults.max_input_tokens is not None
        ):
            data["max_input_tokens"] = defaults.max_input_tokens
        if (
            data.get("max_output_tokens") is None
            and defaults.max_output_tokens is not None
        ):
            max_input_tokens = data.get("max_input_tokens")
            data["max_output_tokens"] = (
                min(int(max_input_tokens), defaults.max_output_tokens)
                if max_input_tokens is not None
                else defaults.max_output_tokens
            )
        return data


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
    # Tenant model fields (required for provider-based architecture)
    tenant_id: Optional[UUID] = None
    provider_id: Optional[UUID] = None
    provider_type: Optional[str] = None

    def _provider_type(self) -> str | None:
        return self.provider_type


class CompletionModelPublic(CompletionModel):
    can_access: bool = False
    is_locked: bool = True
    lock_reason: Optional[str] = None
    credential_provider: Optional[str] = None
    security_classification: Optional[SecurityClassificationPublic] = None
    provider_name: Optional[str] = None

    @classmethod
    def from_domain(cls, completion_model: CompletionModelDomain):
        return cls(
            id=completion_model.id,
            created_at=completion_model.created_at,
            updated_at=completion_model.updated_at,
            name=completion_model.name,
            nickname=completion_model.nickname,
            family=completion_model.family,
            max_input_tokens=completion_model.max_input_tokens,
            max_output_tokens=completion_model.max_output_tokens,
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
            supports_tool_calling=completion_model.supports_tool_calling,
            base_url=completion_model.base_url,
            litellm_model_name=completion_model.litellm_model_name,
            model_kwargs_capabilities=completion_model.model_kwargs_capabilities,
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
            tenant_id=completion_model.tenant_id,
            provider_id=completion_model.provider_id,
            provider_name=completion_model.provider_name,
            provider_type=completion_model.provider_type,
        )


class CompletionModelSecurityStatus(CompletionModelPublic):
    meets_security_classification: Optional[bool] = None


class CompletionModelResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    completion: Union[str, Any]  # Pydantic doesn't support AsyncIterable
    model: CompletionModel
    extended_logging: Optional[LoggingDetails] = None
    total_token_count: int
    knowledge_trace: Optional["KnowledgeTrace"] = None
    usage: Optional[TokenUsage] = None


class MessageToolCall(BaseModel):
    """A replayable tool-use record for the LLM-facing Message.

    Carries only the fields needed to reconstruct OpenAI-style tool_calls +
    role:"tool" result messages in history. The persisted ToolCallInfo
    (intric.questions.question) is a superset — this type deliberately excludes
    approval metadata and non-replayable fields.

    `tool_name` here is the LLM-visible prefixed identifier (e.g.
    `server__tool`) — matching the currently-registered tools — not the
    split/display form that the UI uses.
    """

    tool_call_id: str
    tool_name: str
    arguments: Optional[dict[str, object]] = None
    result: str


class Message(BaseModel):
    question: str
    answer: str
    images: list[File] = []
    generated_images: list[File] = []
    tool_calls: list[MessageToolCall] = []


class KnowledgeTraceGroup(BaseModel):
    source_id: str
    source_id_short: str
    source_title: Optional[str] = None
    start_chunk: int
    end_chunk: int
    chunk_count: int
    relevance_score: Optional[float] = None


class KnowledgeTrace(BaseModel):
    version: int = 1
    selection_basis: str
    raw_source_count: int = 0
    raw_chunk_count: int = 0
    included_source_count: int = 0
    not_included_source_count: int = 0
    included_chunk_count: int = 0
    knowledge_tokens: int = 0
    truncated_by_token_budget: bool = False
    included_source_ids: list[str] = []
    not_included_source_ids: list[str] = []
    included_groups: list[KnowledgeTraceGroup] = []


class Context(BaseModel):
    input: str
    token_count: int = 0
    prompt: str = ""
    messages: list[Message] = []
    images: list[File] = []
    function_definitions: list[FunctionDefinition] = []
    knowledge_trace: Optional[KnowledgeTrace] = None


class ModelKwargs(BaseModel):
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    reasoning_effort: Optional[str] = None
    verbosity: Optional[str] = None
    response_format: Optional[dict[str, object]] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    top_k: Optional[int] = None

    def filter_unsupported(self, supported: SupportedModelKwargs) -> "ModelKwargs":
        # Strip stored values whose capability is currently disabled so a kwarg
        # saved while the capability was enabled (e.g. reasoning_effort on a
        # model whose reasoning flag was later turned off) does not leak to the
        # provider. response_format is intentionally unmanaged here — it is not
        # a SupportedModelKwargs field.
        updates: dict[str, None] = {}
        for field_name in (
            "temperature",
            "top_p",
            "reasoning_effort",
            "verbosity",
            "presence_penalty",
            "frequency_penalty",
            "top_k",
        ):
            capability = getattr(supported, field_name)
            if not capability.supported and getattr(self, field_name) is not None:
                updates[field_name] = None
        if not updates:
            return self
        return self.model_copy(update=updates)


class CompletionModelSparse(CompletionModelBase, InDB):
    provider_type: Optional[str] = None

    def _provider_type(self) -> str | None:
        return self.provider_type
