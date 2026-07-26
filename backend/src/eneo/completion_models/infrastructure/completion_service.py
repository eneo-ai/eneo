from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncGenerator, Literal, Optional, TypeAlias

import redis.asyncio as aioredis

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModel,
    CompletionModelResponse,
    ModelKwargs,
    ResponseType,
)
from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
)
from eneo.completion_models.domain.provider_call_observer import (
    ProviderCallObserver,
    ProviderCallReason,
)
from eneo.completion_models.infrastructure.context_builder import ContextBuilder
from eneo.completion_models.infrastructure.tenant_model_capabilities import (
    StructuredOutputCapabilityDecision,
)
from eneo.files.file_models import File
from eneo.info_blobs.info_blob import InfoBlobChunkInDBWithScore
from eneo.main.config import SETTINGS, Settings, get_settings
from eneo.main.logging import get_logger
from eneo.mcp_servers.infrastructure.proxy import (
    MCPProxySession,
    MCPProxySessionFactory,
)
from eneo.mcp_servers.infrastructure.tool_approval import get_approval_manager
from eneo.sessions.session import SessionInDB
from eneo.settings.encryption_service import EncryptionService
from eneo.tokens.token_utils import log_token_count_drift
from eneo.vision_models.infrastructure.flux_ai import FluxAdapter

if TYPE_CHECKING:
    from eneo.completion_models.domain.completion_model import (
        CompletionModel as DomainCompletionModel,
    )
    from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
        TenantModelAdapter,
    )
    from eneo.completion_models.infrastructure.web_search import WebSearchResult
    from eneo.database.database import AsyncSession
    from eneo.main.container.container import Container
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
    from eneo.settings.encryption_service import EncryptionService
    from eneo.tenants.tenant import TenantInDB

logger = get_logger(__name__)


CompletionEvidenceJsonType: TypeAlias = Literal[
    "null",
    "boolean",
    "integer",
    "number",
    "string",
    "array",
    "object",
    "unknown",
]
CompletionEvidenceFieldDomain: TypeAlias = Literal[
    "credential",
    "endpoint",
    "provider_configuration",
    "route",
    "conversation",
    "tool_contract",
    "tool_selection",
    "transport_control",
    "output_limit",
    "model_control",
]
CompletionCapabilityConstraint: TypeAlias = Literal["none", "range", "options"]


@dataclass(frozen=True, slots=True)
class CompletionEvidenceField:
    """Allowlisted request-shape fact that never carries the field value."""

    name: str
    json_type: CompletionEvidenceJsonType
    domain: CompletionEvidenceFieldDomain

    def to_log_value(self) -> dict[str, object]:
        return {
            "name": self.name,
            "json_type": self.json_type,
            "domain": self.domain,
        }


@dataclass(frozen=True, slots=True)
class CompletionModelKwargCapabilityEvidence:
    name: str
    supported: bool
    json_type: CompletionEvidenceJsonType
    constraint: CompletionCapabilityConstraint

    def to_log_value(self) -> dict[str, object]:
        return {
            "name": self.name,
            "supported": self.supported,
            "json_type": self.json_type,
            "constraint": self.constraint,
        }


@dataclass(frozen=True, slots=True)
class CompletionRouteEvidence:
    """Content-free projection of the effective selected completion route."""

    configuration_fields: tuple[CompletionEvidenceField, ...]
    unclassified_configuration_field_count: int
    model_kwargs_capabilities: tuple[CompletionModelKwargCapabilityEvidence, ...]

    def to_log_value(self) -> dict[str, object]:
        return {
            "source": "resolved_completion_model_route",
            "capability_posture": "trusted_effective",
            "configuration_fields": [
                field.to_log_value() for field in self.configuration_fields
            ],
            "unclassified_configuration_field_count": (
                self.unclassified_configuration_field_count
            ),
            "model_kwargs_capabilities": [
                capability.to_log_value()
                for capability in self.model_kwargs_capabilities
            ],
        }


@dataclass(frozen=True, slots=True)
class ResolvedCompletionModelRoute:
    litellm_model: str
    litellm_kwargs: dict[str, object]
    supported_model_kwargs: SupportedModelKwargs

    def filter_unsupported_model_kwargs(
        self,
        requested: ModelKwargs,
    ) -> dict[str, object]:
        provider_kwargs = {
            key: value
            for key, value in self.litellm_kwargs.items()
            if key not in SupportedModelKwargs.model_fields
        }
        provider_kwargs.update(
            requested.filter_unsupported(self.supported_model_kwargs).model_dump(
                exclude_none=True
            )
        )
        return provider_kwargs

    def incident_evidence(self) -> CompletionRouteEvidence:
        configuration_fields: list[CompletionEvidenceField] = []
        unclassified_configuration_field_count = 0
        for name in sorted(self.litellm_kwargs):
            if name in SupportedModelKwargs.model_fields:
                continue
            domain = completion_evidence_field_domain(name)
            if domain is None:
                unclassified_configuration_field_count += 1
                continue
            configuration_fields.append(
                CompletionEvidenceField(
                    name=name,
                    json_type=completion_evidence_json_type(self.litellm_kwargs[name]),
                    domain=domain,
                )
            )

        capabilities = self.supported_model_kwargs
        capability_specs: tuple[
            tuple[
                str,
                ModelKwargCapability,
                CompletionEvidenceJsonType,
            ],
            ...,
        ] = (
            ("temperature", capabilities.temperature, "number"),
            ("top_p", capabilities.top_p, "number"),
            ("reasoning_effort", capabilities.reasoning_effort, "string"),
            ("verbosity", capabilities.verbosity, "string"),
            ("presence_penalty", capabilities.presence_penalty, "number"),
            ("frequency_penalty", capabilities.frequency_penalty, "number"),
            ("top_k", capabilities.top_k, "integer"),
        )
        model_kwargs_capabilities = tuple(
            CompletionModelKwargCapabilityEvidence(
                name=name,
                supported=capability.supported,
                json_type=json_type,
                constraint=(
                    "options"
                    if capability.options is not None
                    else "range"
                    if capability.minimum is not None or capability.maximum is not None
                    else "none"
                ),
            )
            for name, capability, json_type in capability_specs
        )
        return CompletionRouteEvidence(
            configuration_fields=tuple(configuration_fields),
            unclassified_configuration_field_count=(
                unclassified_configuration_field_count
            ),
            model_kwargs_capabilities=model_kwargs_capabilities,
        )


def completion_evidence_json_type(value: object) -> CompletionEvidenceJsonType:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, Sequence) and not isinstance(value, bytes):
        return "array"
    return "unknown"


def completion_evidence_field_domain(
    name: str,
) -> CompletionEvidenceFieldDomain | None:
    if name in SupportedModelKwargs.model_fields:
        return "model_control"
    if name == "api_key":
        return "credential"
    if name == "api_base":
        return "endpoint"
    if name in {"api_version", "api_type", "organization", "response_format"}:
        return "provider_configuration"
    if name == "drop_params":
        return "transport_control"
    return None


async def generate_image(prompt: str):
    flux = FluxAdapter()

    return await flux.generate_image(prompt=prompt)


@dataclass(frozen=True, slots=True)
class CompletionContextPreview:
    token_count: int
    max_input_tokens: int
    model_route: str


class CompletionService:
    def __init__(
        self,
        context_builder: ContextBuilder,
        tenant: Optional["TenantInDB"] = None,
        config: Optional[Settings] = None,
        encryption_service: Optional["EncryptionService"] = None,
        session: Optional["AsyncSession"] = None,
        redis_client: Optional[aioredis.Redis] = None,
    ):
        self.context_builder = context_builder
        self.tenant = tenant
        self.config = config or SETTINGS
        if encryption_service is None:
            encryption_settings: Settings | None = (
                None if self.config.testing else self.config
            )
            encryption_service = EncryptionService(encryption_settings)
        self.encryption_service = encryption_service
        self.session = session
        self.redis_client = redis_client
        self._mcp_proxy_factory = MCPProxySessionFactory(
            encryption_service=self.encryption_service
        )
        super().__init__()

    async def _get_adapter(
        self,
        model: CompletionModel | DomainCompletionModel,
    ) -> "TenantModelAdapter":
        """
        Get the adapter for the given model.

        All models must have a provider_id linking to a ModelProvider.
        Uses TenantModelAdapter which routes through LiteLLM.
        """
        from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
            TenantModelAdapter,
        )
        from eneo.model_providers.infrastructure.litellm_provider import (
            load_active_litellm_provider,
        )

        # All models must have provider_id
        if not hasattr(model, "provider_id") or not model.provider_id:
            raise ValueError(
                f"Model '{model.name}' is missing required provider_id. "
                "All models must be associated with a ModelProvider."
            )

        # Check if session is available
        if not self.session:
            logger.error(
                "Model requires database session but none available",
                extra={
                    "model_id": str(model.id) if hasattr(model, "id") else None,
                    "model_name": model.name,
                    "provider_id": str(model.provider_id),
                    "tenant_id": str(self.tenant.id) if self.tenant else None,
                },
            )
            raise ValueError(
                f"Model '{model.name}' requires database session to load provider credentials. "
                "Please ensure the CompletionService is initialized with a database session."
            )

        if self.tenant is None:
            raise ValueError(
                f"Model '{model.name}' requires tenant context to load its provider."
            )

        provider = await load_active_litellm_provider(
            session=self.session,
            provider_id=model.provider_id,
            tenant_id=self.tenant.id,
        )
        credential_resolver = provider.create_credential_resolver(
            self.encryption_service
        )

        logger.info(
            f"Using TenantModelAdapter for model '{model.name}'",
            extra={
                "model_id": str(model.id) if hasattr(model, "id") else None,
                "model_name": model.name,
                "provider_id": str(model.provider_id),
                "provider_type": provider.provider_type,
                "tenant_id": str(self.tenant.id) if self.tenant else None,
            },
        )

        return TenantModelAdapter(
            model=model,
            credential_resolver=credential_resolver,
            provider_type=provider.provider_type,
        )

    async def resolve_model_route(
        self,
        model: CompletionModel | DomainCompletionModel,
    ) -> ResolvedCompletionModelRoute:
        adapter = await self._get_adapter(model)
        litellm_model, litellm_kwargs = adapter.resolve_litellm_params()
        return ResolvedCompletionModelRoute(
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            supported_model_kwargs=model.supported_model_kwargs,
        )

    async def resolve_structured_output_capability(
        self,
        model: CompletionModel,
    ) -> StructuredOutputCapabilityDecision:
        adapter = await self._get_adapter(model)
        return adapter.resolve_structured_output_capability()

    @staticmethod
    def is_valid_arguments(arguments: str):
        try:
            # Attempt to parse the string
            parsed = json.loads(arguments)
            # Check if the parsed object is a dictionary
            return isinstance(parsed, dict)
        except (json.JSONDecodeError, TypeError):
            # If there is a JSON decode error or TypeError, return False
            return False

    async def _handle_tool_call(self, completion: AsyncGenerator[Completion]):
        name = None
        arguments = ""
        function_called = False

        async for chunk in completion:
            # Pass through stop chunk (carries usage data)
            if chunk.stop:
                yield chunk
                continue

            # Pass through reasoning/thinking events directly (text=None, so the
            # branches below would otherwise drop them before they reach SSE).
            if chunk.response_type == ResponseType.REASONING:
                yield chunk
                continue

            # Pass through MCP tool call events directly
            if chunk.response_type == ResponseType.TOOL_CALL:
                yield chunk
                continue

            # Pass through tool approval required events directly
            if chunk.response_type == ResponseType.TOOL_APPROVAL_REQUIRED:
                yield chunk
                continue

            if chunk.tool_call:
                if chunk.tool_call.name:
                    name = chunk.tool_call.name

                if chunk.tool_call.arguments:
                    arguments += chunk.tool_call.arguments

                if not name or not arguments or not self.is_valid_arguments(arguments):
                    # Keep collecting the tool call
                    continue
                elif not function_called:
                    call_args = json.loads(arguments)

                    if name == "generate_image":
                        yield Completion(response_type=ResponseType.ENEO_EVENT)

                        chunk.image_data = await generate_image(**call_args)  # type: ignore[attr-defined]
                        chunk.response_type = ResponseType.FILES

                        yield chunk

                    function_called = True

            elif chunk.text:
                chunk.response_type = ResponseType.TEXT

                yield chunk

    async def preview_context(
        self,
        *,
        model: CompletionModel,
        text_input: str,
        files: list[File] | None = None,
        prompt: str = "",
        prompt_files: list[File] | None = None,
        version: int = 1,
    ) -> CompletionContextPreview:
        """Package and count one request without provider, embedding, or MCP I/O."""
        model_adapter = await self._get_adapter(model)
        model_route = model_adapter.get_model_route()
        max_tokens = model_adapter.get_token_limit_of_model()
        context = self.context_builder.build_context(
            input_str=text_input,
            max_tokens=max_tokens,
            model_name=model_route,
            files=files or [],
            prompt=prompt,
            session=None,
            info_blob_chunks=[],
            prompt_files=prompt_files or [],
            transcription_inputs=[],
            version=version,
            use_image_generation=False,
            web_search_results=[],
            vision=model.vision,
            extra_tool_dicts=None,
            reject_over_limit=True,
        )
        return CompletionContextPreview(
            token_count=context.token_count,
            max_input_tokens=max_tokens,
            model_route=model_route,
        )

    async def get_response(
        self,
        model: CompletionModel,
        text_input: str,
        model_kwargs: ModelKwargs | None = None,
        files: list[File] | None = None,
        prompt: str = "",
        prompt_files: list[File] | None = None,
        transcription_inputs: list[str] | None = None,
        info_blob_chunks: list[InfoBlobChunkInDBWithScore] | None = None,
        web_search_results: list["WebSearchResult"] | None = None,
        session: SessionInDB | None = None,
        stream: bool = False,
        extended_logging: bool = False,
        version: int = 1,
        use_image_generation: bool = False,
        mcp_servers: list["MCPServer"] | None = None,
        require_tool_approval: bool = False,
        reject_context_over_limit: bool = False,
        provider_call_observer: ProviderCallObserver | None = None,
        provider_call_reason: ProviderCallReason = "initial",
    ) -> CompletionModelResponse:
        if files is None:
            files = []
        if prompt_files is None:
            prompt_files = []
        if transcription_inputs is None:
            transcription_inputs = []
        if info_blob_chunks is None:
            info_blob_chunks = []
        if web_search_results is None:
            web_search_results = []
        if mcp_servers is None:
            mcp_servers = []
        if stream and provider_call_observer is not None:
            raise ValueError(
                "Provider call observation is only supported for non-streaming requests."
            )
        # Org-level disable must be honored at runtime. Disabling a server only
        # flips MCPServers.is_enabled (mcp_server_settings_service); the existing
        # assistant->server associations are never pruned, so a disabled server
        # can still reach this point attached to an assistant (or help assistant).
        # This is the single boundary where MCP servers are connected and their
        # tools exposed to the model, so filter here: a disabled server is never
        # connected, and if every server is disabled no proxy is created at all.
        # The governed personal-default path already filters is_enabled upstream
        # (effective_config_service), so re-filtering here is idempotent.
        mcp_servers = [server for server in mcp_servers if server.is_enabled]
        model_adapter = await self._get_adapter(model)
        if model_kwargs is not None:
            model_kwargs = model_kwargs.filter_unsupported(model.supported_model_kwargs)

        # Make sure everything fits in the context of the model
        max_tokens = model_adapter.get_token_limit_of_model()

        # Image generation only works on streaming for now
        # And only if feature flag is turned on
        use_image_generation = (
            use_image_generation and stream and get_settings().using_image_generation
        )

        # Create MCP proxy session before building the context, so the tool
        # definitions it will register can be counted toward the token budget.
        # Pass the chat session id + active DB session so each MCP server's
        # protocol-assigned ``mcp-session-id`` resumes across user turns
        # (persisted in ``chat_session_mcp_state``). Behavior is identical for
        # every MCP server, with no per-server-kind branching.
        mcp_proxy: MCPProxySession | None = None
        if mcp_servers:
            mcp_proxy = self._mcp_proxy_factory.create(
                mcp_servers,
                chat_session_id=session.id if session is not None else None,
                db_session=self.session,
            )
            logger.debug(
                f"[MCP] Proxy created with {mcp_proxy.get_tool_count()} tools from {len(mcp_servers)} server(s)"
            )

        try:
            context = self.context_builder.build_context(
                input_str=text_input,
                max_tokens=max_tokens,
                model_name=model_adapter.get_model_route(),
                files=files,
                prompt=prompt,
                session=session,
                info_blob_chunks=info_blob_chunks,
                prompt_files=prompt_files,
                transcription_inputs=transcription_inputs,
                version=version,
                use_image_generation=use_image_generation,
                web_search_results=web_search_results,
                vision=model.vision,
                extra_tool_dicts=(
                    mcp_proxy.get_tools_for_llm()
                    if mcp_proxy and model.supports_tool_calling
                    else None
                ),
                reject_over_limit=reject_context_over_limit,
            )

            if extended_logging:
                logging_details = model_adapter.get_logging_details(
                    context=context, model_kwargs=model_kwargs
                )
            else:
                logging_details = None
        except BaseException:
            # Context building can still raise on malformed input or dependencies.
            # The proxy is closed in the streaming/non-streaming paths below, but
            # those are never reached on failure here.
            if mcp_proxy:
                await mcp_proxy.close()
            raise

        if not stream:
            try:
                completion = await model_adapter.get_response(
                    context=context,
                    model_kwargs=model_kwargs,
                    mcp_proxy=mcp_proxy,
                    provider_call_observer=provider_call_observer,
                    provider_call_reason=provider_call_reason,
                )
            finally:
                # Ensure cleanup for non-streaming
                if mcp_proxy:
                    await mcp_proxy.close()
        else:
            # Two-phase streaming pattern:
            # Phase 1: Create stream connection BEFORE returning (can raise exceptions)
            # This happens eagerly, so exceptions propagate before HTTP response starts
            try:
                stream_obj = await model_adapter.prepare_streaming(
                    context=context,
                    model_kwargs=model_kwargs,
                    mcp_proxy=mcp_proxy,
                )
            except BaseException:
                # If stream prep fails, close the proxy here — the streaming_wrapper's
                # finally block won't run because the generator is never reached.
                # Without this, leaked MCP connections accumulate anyio task-group
                # background tasks and creep CPU toward 100% over the worker's lifetime.
                if mcp_proxy:
                    await mcp_proxy.close()
                raise

            # Phase 2: Create generator that iterates the pre-created stream
            # This generator yields error events for mid-stream failures
            async def streaming_wrapper() -> AsyncGenerator[Completion, None]:
                """
                Generator that iterates pre-created stream.
                The stream was already created and validated, so we're past
                the pre-flight checks. Any errors here are mid-stream failures.
                Proxy cleanup happens after iteration completes.
                """
                approval_manager: Any | None = None
                pending_approval_ids: set[str] = set()
                approval_context = None
                try:
                    # Get approval manager if tool approval is required
                    if require_tool_approval:
                        approval_manager = get_approval_manager(
                            redis_client=self.redis_client
                        )
                    if require_tool_approval:
                        if session is None:
                            raise ValueError(
                                "Tool approval requires an active conversation session"
                            )
                        if self.tenant is None:
                            raise ValueError("Tool approval requires tenant context")
                        approval_context = {
                            "tenant_id": self.tenant.id,
                            "user_id": session.user_id,
                            "session_id": session.id,
                            "assistant_id": (
                                session.assistant.id
                                if session.assistant is not None
                                else None
                            ),
                        }

                    async for chunk in model_adapter.iterate_stream(
                        stream=stream_obj,
                        context=context,
                        model_kwargs=model_kwargs,
                        require_tool_approval=require_tool_approval,
                        approval_manager=approval_manager,
                        approval_context=approval_context,
                        pending_approval_ids=pending_approval_ids,
                    ):
                        yield chunk
                finally:
                    if approval_manager:
                        for approval_id in list(pending_approval_ids):
                            try:
                                await approval_manager.cancel_approval(approval_id)
                            except Exception:
                                logger.warning(
                                    "Failed to cancel pending tool approval",
                                    extra={"approval_id": approval_id},
                                    exc_info=True,
                                )

                    # Cleanup proxy after streaming completes
                    if mcp_proxy:
                        await mcp_proxy.close()

            completion = self._handle_tool_call(streaming_wrapper())

        usage = getattr(completion, "usage", None) if not stream else None
        if usage is not None:
            log_token_count_drift(
                model_name=model_adapter.get_model_route(),
                predicted=context.token_count,
                actual=usage.prompt_tokens,
            )

        return CompletionModelResponse(
            completion=completion,
            model=model,
            extended_logging=logging_details,
            total_token_count=context.token_count,
            usage=usage,
        )


class CompletionServiceFactory:
    def __init__(self, container: Container):
        self.container = container
        super().__init__()
