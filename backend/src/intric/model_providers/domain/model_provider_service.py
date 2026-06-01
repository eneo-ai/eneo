from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID, uuid4

from intric.main.exceptions import NameCollisionException
from intric.model_providers.domain.model_provider import ModelProvider
from intric.model_providers.infrastructure.model_provider_repository import (
    ModelProviderRepository,
)
from intric.settings.encryption_service import EncryptionService

if TYPE_CHECKING:
    pass


# Default base URLs for providers that don't ask the user for one.
# Any provider configured with its own ``endpoint`` wins over the default.
_DEFAULT_ENDPOINTS: dict[str, str] = {
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
}


def _auth_headers_for(provider_type: str, api_key: str) -> dict[str, str]:
    """Auth header set per provider. Bearer for everyone except Anthropic,
    which uses its own header pair."""
    if provider_type == "anthropic":
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {api_key}"}


def _normalize_endpoint_base(base: str) -> str:
    """Strip a trailing slash and an optional ``/v1`` suffix so users can
    paste either ``https://api.example.com`` or ``https://api.example.com/v1``
    without us producing ``/v1/v1/models``."""
    s = base.rstrip("/")
    if s.endswith("/v1"):
        s = s[:-3].rstrip("/")
    return s


def _coerce_to_epoch(value: Any) -> float:
    """Best-effort parse of a created/release timestamp into epoch seconds.
    Accepts an int/float (already epoch), an ISO 8601 string, or returns 0.0
    for anything else so models without a timestamp sort last."""
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


def _extract_mode_hint(m: dict[str, Any]) -> str | None:
    """Read mode classification from provider-supplied response metadata.

    Some providers expose richer fields than just ``id`` — read them
    opportunistically. When present, these are far more reliable than
    name-based heuristics (``intfloat/multilingual-e5-large`` is an
    embedding model whose name doesn't say so). Sources, in priority order:

    1. ``model_type`` — coarse category. Values seen in the wild:
       ``"embedding"``, ``"text"``, ``"audio"``/``"transcription"``.
    2. ``capabilities.embeddings: true`` — fallback for providers that
       use ``model_type: "text"`` for everything and rely on the flag.

    Returns one of ``"completion"``, ``"embedding"``, ``"transcription"``,
    or ``None`` when the response carries neither field and the caller
    should fall back to name-based inference.
    """
    raw_capabilities: Any = m.get("capabilities")
    embeddings_flag: bool = (
        isinstance(raw_capabilities, dict)
        and raw_capabilities.get("embeddings") is True  # type: ignore[reportUnknownMemberType]
    )

    model_type = m.get("model_type")
    if model_type == "embedding":
        return "embedding"
    if model_type in ("audio", "transcription"):
        return "transcription"
    if model_type == "text":
        # Could still be an embedding flagged via capabilities.
        return "embedding" if embeddings_flag else "completion"

    if embeddings_flag:
        return "embedding"

    return None


def _normalize_live_model(m: dict[str, Any]) -> dict[str, Any]:
    """Normalize a single ``/v1/models`` entry across providers.

    Pull each field with a fallback chain so any provider that follows the
    same rough shape works without a code change. Field variants seen in
    the wild: ``display_name``/``name`` for the friendly label;
    ``created_at`` (ISO) / ``created`` (epoch) / ``release_date`` for
    the timestamp; richer providers also include ``capabilities`` and
    ``model_type`` which we read via ``_extract_mode_hint``.
    """
    return {
        "id": m["id"],
        "display_name": m.get("display_name") or m.get("name", ""),
        "created_at": _coerce_to_epoch(
            m.get("created_at") or m.get("created") or m.get("release_date")
        ),
        "mode_hint": _extract_mode_hint(m),
    }


# LiteLLM mode → our model_type. Anything else (image, tts, moderation) is filtered out.
_LITELLM_MODE_TO_OUR_MODE: dict[str, str] = {
    "chat": "completion",
    "completion": "completion",
    "embedding": "embedding",
    "audio_transcription": "transcription",
}

# Name substrings to drop — same set the static capabilities endpoint filters.
# These run on every name regardless of whether it appears in litellm.model_cost,
# i.e. they catch known-but-unwanted models (preview snapshots, audio variants).
# This is intentionally kept separate from the keyword list inside
# `_infer_mode_from_name`, which only runs on cache misses to *classify* an
# unknown name's mode (e.g. "whisper-2" → transcription, "dall-e-99" → drop).
_NAME_FILTER_SUBSTRINGS: tuple[str, ...] = (
    "realtime",
    "-audio-",
    "gpt-audio",
    "search-preview",
    "search-api",
    "-diarize",
)


def _infer_mode_from_name(name: str) -> str | None:
    """Best-effort mode inference for names not in litellm.model_cost.

    This is only invoked for names that arrived via a live ``/v1/models``
    response — i.e. the provider has already asserted they serve this
    model. Image/audio/moderation names are still dropped from the picker;
    everything else defaults to ``"completion"`` since the alternative
    (returning None and dropping the entry) silently hides real models
    from any provider whose names don't match a hardcoded prefix.
    """
    lower = name.lower()
    if any(kw in lower for kw in ("dall-e", "tts-", "moderation")):
        return None
    if "whisper" in lower:
        return "transcription"
    if "embedding" in lower:
        return "embedding"
    return "completion"


def _enrich_with_litellm_metadata(
    name: str, provider_type: str, mode_hint: str | None = None
) -> dict[str, Any] | None:
    """Look up `name` in litellm.model_cost (with prefix variants) and return
    an enriched capability dict, or None if the model should be hidden.

    Returns None when the name matches a non-text filter substring or maps to
    a litellm mode we don't surface (image, tts, moderation, etc.).

    When the name isn't in the cost map, ``mode_hint`` (read from the
    provider's own response — see ``_extract_mode_hint``) wins over name
    inference, so embedding models with non-obvious names like
    ``intfloat/multilingual-e5-large`` get classified correctly.
    """
    import litellm

    lower = name.lower()
    if any(kw in lower for kw in _NAME_FILTER_SUBSTRINGS):
        return None
    if name.endswith("-latest") or "/container" in lower:
        return None

    model_cost = getattr(litellm, "model_cost", {})

    candidates = [name, f"{provider_type}/{name}"]
    info: dict[str, Any] | None = None
    for key in candidates:
        if key in model_cost:
            info = model_cost[key]
            break

    if info is None:
        chosen = mode_hint or _infer_mode_from_name(name)
        if chosen is None:
            return None
        return {"name": name, "mode": chosen}

    litellm_mode = info.get("mode", "")
    mode = _LITELLM_MODE_TO_OUR_MODE.get(litellm_mode)
    if mode is None:
        return None

    enriched: dict[str, Any] = {"name": name, "mode": mode}
    if mode == "completion":
        enriched["max_input_tokens"] = info.get("max_input_tokens")
        enriched["max_output_tokens"] = info.get("max_output_tokens")
        enriched["supports_vision"] = info.get("supports_vision", False)
        enriched["supports_function_calling"] = info.get(
            "supports_function_calling", False
        )
        enriched["supports_reasoning"] = info.get("supports_reasoning", False)
        enriched["input_cost_per_token"] = info.get("input_cost_per_token")
        enriched["output_cost_per_token"] = info.get("output_cost_per_token")
    elif mode == "embedding":
        enriched["max_input_tokens"] = info.get("max_input_tokens")
        enriched["output_vector_size"] = info.get("output_vector_size")
        enriched["input_cost_per_token"] = info.get("input_cost_per_token")
        enriched["output_cost_per_token"] = info.get("output_cost_per_token")
    elif mode == "transcription":
        # LiteLLM stores transcription rates per second on most entries
        # (Whisper et al.); surface a per-minute view for the form.
        input_per_second = info.get("input_cost_per_second")
        if isinstance(input_per_second, (int, float)):
            enriched["cost_per_minute"] = input_per_second * 60
    return enriched


class ModelProviderService:
    """Service for managing model providers with credential encryption."""

    def __init__(
        self, repository: ModelProviderRepository, encryption: EncryptionService
    ):
        super().__init__()
        self.repository = repository
        self.encryption = encryption

    def _encrypt_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        """Encrypt sensitive credential fields."""
        encrypted_creds = credentials.copy()

        # Encrypt API key if present
        if "api_key" in encrypted_creds and encrypted_creds["api_key"]:
            encrypted_creds["api_key"] = self.encryption.encrypt(
                encrypted_creds["api_key"]
            )

        # Add more credential fields here if needed in the future
        # e.g., client_secret, access_token, etc.

        return encrypted_creds

    def _decrypt_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        """Decrypt sensitive credential fields."""
        decrypted_creds = credentials.copy()

        # Decrypt API key if present
        if "api_key" in decrypted_creds and decrypted_creds["api_key"]:
            decrypted_creds["api_key"] = self.encryption.decrypt(
                decrypted_creds["api_key"]
            )

        return decrypted_creds

    async def get_all(self, active_only: bool = False) -> list[ModelProvider]:
        """Get all providers for the tenant."""
        return await self.repository.all(active_only=active_only)

    async def get_by_id(self, provider_id: UUID) -> ModelProvider:
        """Get a provider by ID."""
        return await self.repository.get_by_id(provider_id)

    @staticmethod
    def _validate_required_fields(
        provider_type: str,
        credentials: dict[str, Any],
        config: dict[str, Any],
    ) -> None:
        """Validate that all required fields are present for the provider type."""
        from intric.tenants.provider_field_config import get_field_definitions

        field_defs = get_field_definitions(provider_type)
        for field in field_defs:
            if field["required"]:
                source = credentials if field["in_"] == "credentials" else config
                value = source.get(field["name"])
                if not value or (isinstance(value, str) and not value.strip()):
                    raise ValueError(
                        f"Field '{field['name']}' is required for provider '{provider_type}'"
                    )

    async def create(
        self,
        tenant_id: UUID,
        name: str,
        provider_type: str,
        credentials: dict[str, Any],
        config: dict[str, Any],
        is_active: bool = True,
    ) -> ModelProvider:
        """Create a new provider."""
        # Check for duplicate names
        existing = await self.repository.get_by_name(name)
        if existing is not None:
            raise NameCollisionException(f"Provider with name '{name}' already exists")

        # Validate required fields for this provider type
        self._validate_required_fields(provider_type, credentials, config)

        # Encrypt credentials before storing
        encrypted_credentials = self._encrypt_credentials(credentials)

        # Create domain entity
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        provider = ModelProvider(
            id=uuid4(),
            tenant_id=tenant_id,
            name=name,
            provider_type=provider_type,
            credentials=encrypted_credentials,
            config=config,
            is_active=is_active,
            created_at=now,
            updated_at=now,
        )

        return await self.repository.create(provider)

    async def update(
        self,
        provider_id: UUID,
        name: Optional[str] = None,
        credentials: Optional[dict[str, Any]] = None,
        config: Optional[dict[str, Any]] = None,
        is_active: Optional[bool] = None,
    ) -> ModelProvider:
        """Update an existing provider."""
        # Get existing provider
        provider = await self.repository.get_by_id(provider_id)

        # Check for duplicate names if name is being changed
        if name is not None and name != provider.name:
            existing = await self.repository.get_by_name(name)
            if existing is not None:
                raise NameCollisionException(
                    f"Provider with name '{name}' already exists"
                )
            provider.name = name

        if credentials is not None:
            provider.credentials = self._encrypt_credentials(credentials)

        if config is not None:
            # Merge with existing config so unchanged fields are preserved
            merged = {**provider.config, **config}
            provider.config = merged

        if is_active is not None:
            provider.is_active = is_active

        return await self.repository.update(provider)

    async def delete(self, provider_id: UUID) -> None:
        """Delete a provider.

        Raises:
            ValueError: If the provider has models attached to it
        """
        # Check if provider has any models
        model_count = await self.repository.count_models_for_provider(provider_id)
        if model_count > 0:
            raise ValueError(
                f"Cannot delete provider: {model_count} model(s) are using this provider. "
                "Delete the models first."
            )

        await self.repository.delete(provider_id)

    async def get_decrypted_credentials(self, provider_id: UUID) -> dict[str, Any]:
        """Get decrypted credentials for a provider (for internal use only)."""
        provider = await self.repository.get_by_id(provider_id)
        return self._decrypt_credentials(provider.credentials)

    async def validate_model(
        self, provider_id: UUID, model_name: str, model_type: str
    ) -> dict[str, Any]:
        """Validate a model by making a minimal LiteLLM call.

        For completion models: sends a single-token completion request.
        For embedding models: sends a minimal embedding request.
        For transcription models: skips validation (requires audio file).
        """
        if model_type == "transcription":
            return {
                "success": True,
                "message": "Validation skipped for transcription models",
            }

        import litellm

        provider = await self.repository.get_by_id(provider_id)
        decrypted_creds = self._decrypt_credentials(provider.credentials)
        api_key = decrypted_creds.get("api_key", "")
        provider_type = provider.provider_type.lower()

        # Build the litellm model identifier
        # For vLLM, use hosted_vllm prefix for litellm compliance
        if provider_type == "vllm":
            litellm_model = f"hosted_vllm/{model_name}"
        elif provider_type == "azure":
            litellm_model = f"azure/{model_name}"
        else:
            litellm_model = f"{provider_type}/{model_name}"

        kwargs: dict[str, Any] = {"model": litellm_model, "api_key": api_key}

        # Add provider-specific config
        if provider_type == "azure":
            kwargs["api_base"] = provider.config.get("endpoint", "")
            kwargs["api_version"] = provider.config.get(
                "api_version", "2024-02-15-preview"
            )
        elif provider_type in ("vllm",) or provider.config.get("endpoint"):
            kwargs["api_base"] = provider.config.get("endpoint", "")

        aembedding: Any = getattr(litellm, "aembedding")
        acompletion: Any = getattr(litellm, "acompletion")

        try:
            if model_type == "embedding":
                await aembedding(input=["test"], **kwargs)
            else:
                await acompletion(
                    messages=[{"role": "user", "content": "hi"}],
                    max_completion_tokens=10,
                    drop_params=True,
                    **kwargs,
                )
            return {"success": True, "message": "Model validated successfully"}
        except Exception as e:
            error_name = e.__class__.__name__
            if error_name == "AuthenticationError":
                return {"success": False, "error": "Invalid API key"}
            if error_name == "NotFoundError":
                return {"success": False, "error": f"Model not found: {model_name}"}
            if error_name == "APIConnectionError":
                return {"success": False, "error": "Could not connect to API"}
            return {"success": False, "error": f"Validation failed: {str(e)}"}

    async def _fetch_live_models(
        self, provider_type: str, api_key: str, endpoint: str
    ) -> list[dict[str, Any]]:
        """Fetch the live model list from a provider.

        Most providers expose ``GET /v1/models`` returning
        ``{"data": [{"id": ...}]}``. The two things that vary are the auth
        header and the base URL — captured by ``_auth_headers_for`` and
        ``_DEFAULT_ENDPOINTS``. Fields beyond ``id`` are pulled
        opportunistically through fallback chains in ``_normalize_live_model``
        so providers with richer responses get more metadata, while
        minimal-shape providers still work.

        Returns entries with ``id``, optional ``display_name``, a
        ``created_at`` epoch-seconds value used to sort newest-first, and
        an optional ``mode_hint`` from provider-supplied capability fields.
        Azure is skipped — its ``/openai/models`` returns every model in
        the region, not deployed ones.
        """
        import httpx

        if provider_type == "azure":
            return []

        base = endpoint or _DEFAULT_ENDPOINTS.get(provider_type)
        if not base:
            return []

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{_normalize_endpoint_base(base)}/v1/models",
                headers=_auth_headers_for(provider_type, api_key),
            )
            resp.raise_for_status()
            return [_normalize_live_model(m) for m in resp.json().get("data", [])]

    async def list_available_models(
        self, provider_id: UUID, mode: str | None = None
    ) -> list[dict[str, Any]]:
        """List models available on a provider using its credentials, enriched
        with capability metadata from litellm.model_cost.

        Each entry has at least ``name`` and ``mode`` (one of "completion",
        "embedding", "transcription"). Completion entries include
        ``max_input_tokens``, ``max_output_tokens``, and ``supports_*``
        flags; embedding entries include ``max_input_tokens`` and
        ``output_vector_size``.

        Pass ``mode`` to filter the response to a single category — keeps
        consumers (frontend pickers, external API clients) from having to
        filter client-side.
        """
        provider = await self.repository.get_by_id(provider_id)
        decrypted_creds = self._decrypt_credentials(provider.credentials)
        api_key = decrypted_creds.get("api_key", "")
        provider_type = provider.provider_type.lower()
        endpoint = provider.config.get("endpoint", "")

        try:
            items = await self._fetch_live_models(provider_type, api_key, endpoint)
        except Exception as e:
            return [{"error": f"Failed to list models: {str(e)}"}]

        # Sort newest-first by provider-supplied created_at, with id as a
        # stable tiebreaker so models without a timestamp keep alphabetical order.
        sorted_items = sorted(
            items, key=lambda x: (-float(x.get("created_at", 0) or 0), x["id"])
        )

        enriched: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in sorted_items:
            name = item["id"]
            if name in seen:
                continue
            seen.add(name)
            entry = _enrich_with_litellm_metadata(
                name, provider_type, mode_hint=item.get("mode_hint")
            )
            if entry is None:
                continue
            if mode is not None and entry.get("mode") != mode:
                continue
            display_name = item.get("display_name")
            if display_name:
                entry["display_name"] = display_name
            enriched.append(entry)
        return enriched

    async def test_connection(self, provider_id: UUID) -> dict[str, Any]:
        """Test connectivity to a model provider by making a minimal LiteLLM call.

        Tries multiple test models per provider as fallback in case older models
        have been deprecated.
        """
        import litellm

        acompletion: Any = getattr(litellm, "acompletion")

        provider = await self.repository.get_by_id(provider_id)
        decrypted_creds = self._decrypt_credentials(provider.credentials)
        api_key = decrypted_creds.get("api_key", "")

        provider_type = provider.provider_type.lower()
        base_kwargs: dict[str, Any] = {
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
            "api_key": api_key,
        }

        # Multiple candidates per provider, ordered from cheapest/newest to oldest.
        # If a model is retired, the next one in the list is tried.
        test_model_candidates: dict[str, list[str]] = {
            "openai": [
                "openai/gpt-4o-mini",
                "openai/gpt-4.1-nano",
                "openai/gpt-3.5-turbo",
            ],
            "anthropic": [
                "anthropic/claude-3-5-haiku-20241022",
                "anthropic/claude-3-haiku-20240307",
                "anthropic/claude-3-5-sonnet-20241022",
            ],
            "gemini": [
                "gemini/gemini-2.0-flash",
                "gemini/gemini-1.5-flash",
                "gemini/gemini-pro",
            ],
            "cohere": [
                "cohere/command-r",
                "cohere/command-r-plus",
                "cohere/command",
            ],
            "mistral": [
                "mistral/mistral-small-latest",
                "mistral/mistral-tiny",
                "mistral/open-mistral-7b",
            ],
        }

        # Azure and vLLM use provider config, not a candidate list
        if provider_type == "azure":
            deployment = provider.config.get("deployment_name", "gpt-4o-mini")
            base_kwargs["model"] = f"azure/{deployment}"
            base_kwargs["api_base"] = provider.config.get("endpoint", "")
            base_kwargs["api_version"] = provider.config.get(
                "api_version", "2024-02-15-preview"
            )
            candidates = [base_kwargs["model"]]
        elif provider_type == "vllm":
            base_kwargs["api_base"] = provider.config.get("endpoint", "")
            candidates = ["openai/test"]
        elif provider_type in test_model_candidates:
            candidates = test_model_candidates[provider_type]
        else:
            model_name = provider.config.get("model_name", "test")
            if provider.config.get("endpoint"):
                base_kwargs["api_base"] = provider.config["endpoint"]
            candidates = [f"openai/{model_name}"]

        for model in candidates:
            kwargs = {**base_kwargs, "model": model}
            try:
                await acompletion(**kwargs)
                return {"success": True, "message": "Connection successful"}
            except Exception as e:
                error_name = e.__class__.__name__
                if error_name == "AuthenticationError":
                    return {"success": False, "error": "Invalid API key"}
                if error_name == "APIConnectionError":
                    return {"success": False, "error": "Could not connect to the API"}
                if error_name == "NotFoundError":
                    # Model not found — try next candidate
                    continue
                # For non-model errors, no point retrying with a different model
                return {"success": False, "error": f"Connection test failed: {str(e)}"}

        # All candidates returned NotFound
        return {
            "success": False,
            "error": (
                "None of the test models could be found. "
                "The provider may not support completion models, "
                "or the API endpoint may be misconfigured."
            ),
        }
