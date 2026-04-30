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


# LiteLLM mode → our model_type. Anything else (image, tts, moderation) is filtered out.
_LITELLM_MODE_TO_OUR_MODE: dict[str, str] = {
    "chat": "completion",
    "completion": "completion",
    "embedding": "embedding",
    "audio_transcription": "transcription",
}

# Name substrings to drop — same set the static capabilities endpoint filters.
_NAME_FILTER_SUBSTRINGS: tuple[str, ...] = (
    "realtime",
    "-audio-",
    "gpt-audio",
    "search-preview",
    "search-api",
    "-diarize",
)


def _infer_mode_from_name(name: str, provider_type: str) -> str | None:
    """Best-effort mode inference for names not in litellm.model_cost.

    Returns None when the name clearly maps to a non-text mode (image, tts,
    moderation) so the entry is dropped. Returns "completion" by default for
    Anthropic (their /v1/models only returns chat models). Returns None for
    fully unknown names so we don't pollute mode-specific pickers.
    """
    lower = name.lower()
    if any(kw in lower for kw in ("dall-e", "image", "tts-", "moderation", "whisper")):
        if "whisper" in lower:
            return "transcription"
        return None
    if "embedding" in lower:
        return "embedding"
    if provider_type == "anthropic":
        return "completion"
    if lower.startswith(("gpt-", "o1", "o3", "o4", "chatgpt-")):
        return "completion"
    return None


def _enrich_with_litellm_metadata(
    name: str, provider_type: str
) -> dict[str, Any] | None:
    """Look up `name` in litellm.model_cost (with prefix variants) and return
    an enriched capability dict, or None if the model should be hidden.

    Returns None when the name matches a non-text filter substring or maps to
    a litellm mode we don't surface (image, tts, moderation, etc.).

    For names not present in the cost map, falls back to mode inference from
    the name so newly-released models still show up. Returns None if no mode
    can be inferred (avoids polluting mode-specific pickers with unknowns).
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
        inferred = _infer_mode_from_name(name, provider_type)
        if inferred is None:
            return None
        return {"name": name, "mode": inferred}

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
    elif mode == "embedding":
        enriched["max_input_tokens"] = info.get("max_input_tokens")
        enriched["output_vector_size"] = info.get("output_vector_size")
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

    async def _fetch_live_model_names(
        self, provider_type: str, api_key: str, endpoint: str
    ) -> list[str]:
        """Fetch the list of model names available on a provider via its own API."""
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            if provider_type == "azure":
                # Azure /openai/models returns all models in the region, not
                # just deployed ones. Users enter their deployment name manually.
                return []

            if provider_type == "openai":
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                resp.raise_for_status()
                return [m["id"] for m in resp.json().get("data", [])]

            if provider_type == "anthropic":
                resp = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                    },
                )
                resp.raise_for_status()
                return [m["id"] for m in resp.json().get("data", [])]

            # OpenAI-compatible providers (vLLM, custom endpoints)
            if endpoint:
                resp = await client.get(
                    f"{endpoint.rstrip('/')}/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                resp.raise_for_status()
                return [m["id"] for m in resp.json().get("data", [])]

            return []

    async def list_available_models(self, provider_id: UUID) -> list[dict[str, Any]]:
        """List models available on a provider using its credentials, enriched
        with capability metadata from litellm.model_cost.

        Each entry has at least ``name`` and ``mode`` (one of "completion",
        "embedding", "transcription", or None for unknown). Completion entries
        include ``max_input_tokens``, ``max_output_tokens``, and ``supports_*``
        flags; embedding entries include ``max_input_tokens`` and
        ``output_vector_size``.
        """
        provider = await self.repository.get_by_id(provider_id)
        decrypted_creds = self._decrypt_credentials(provider.credentials)
        api_key = decrypted_creds.get("api_key", "")
        provider_type = provider.provider_type.lower()
        endpoint = provider.config.get("endpoint", "")

        try:
            names = await self._fetch_live_model_names(provider_type, api_key, endpoint)
        except Exception as e:
            return [{"error": f"Failed to list models: {str(e)}"}]

        enriched: list[dict[str, Any]] = []
        seen: set[str] = set()
        for name in sorted(names):
            if name in seen:
                continue
            seen.add(name)
            entry = _enrich_with_litellm_metadata(name, provider_type)
            if entry is not None:
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
