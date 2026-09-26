from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional
from uuid import UUID, uuid4

from eneo.main.exceptions import (
    BadRequestException,
    EncryptionNotConfiguredException,
    NameCollisionException,
)
from eneo.model_providers.domain.connection_check import (
    ConnectionCheck,
    ConnectionCheckError,
)
from eneo.model_providers.domain.model_defaults_lookup import resolve_model_defaults
from eneo.model_providers.domain.model_provider import ModelProvider
from eneo.model_providers.domain.provider_api import (
    configured_endpoint,
    connection_check_request,
    models_list_request,
)
from eneo.model_providers.infrastructure.model_provider_repository import (
    ModelProviderRepository,
)
from eneo.model_providers.infrastructure.provider_connection_probe import (
    probe_connection,
)
from eneo.settings.encryption_service import EncryptionService
from eneo.tenants.provider_field_config import is_field_required


class Unchanged(Enum):
    """An update argument the caller did not send, where None means "clear"."""

    UNCHANGED = "unchanged"


UNCHANGED = Unchanged.UNCHANGED


class ConnectionCheckNotSupportedException(BadRequestException):
    """No cheap authenticated call is known for this provider."""


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
    ``"image"``, or ``None`` when the response carries neither field and the
    caller should fall back to name-based inference.
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
    if model_type in ("image", "image_generation"):
        return "image"
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


# LiteLLM mode → our model_type. Anything else (tts, moderation, ...) is
# filtered out. Shared with the capabilities endpoint so the two cannot drift.
LITELLM_MODE_TO_OUR_MODE: dict[str, str] = {
    "chat": "completion",
    "completion": "completion",
    "embedding": "embedding",
    "audio_transcription": "transcription",
    "image_generation": "image",
}

# Name fragments that mark an image generation model when the name is not in
# litellm.model_cost (self-hosted or brand-new models). Heuristic only: the
# admin can always type a name the picker did not suggest.
_IMAGE_NAME_KEYWORDS: tuple[str, ...] = (
    "dall-e",
    "gpt-image",
    "imagen",
    "stable-diffusion",
    "sdxl",
    "flux",
    "-image",
)


def per_image_cost(info: dict[str, Any]) -> float | None:
    """Flat USD price per generated image from a litellm.model_cost entry.

    Providers that price per image put it under ``output_cost_per_image``
    (Imagen) or ``input_cost_per_image`` (DALL-E). Token-priced image models
    (gpt-image-1) have neither and return None: the admin fills in a figure.
    """
    for key in ("output_cost_per_image", "input_cost_per_image"):
        value = info.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


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
    model. Speech and moderation names are still dropped from the picker;
    everything else defaults to ``"completion"`` since the alternative
    (returning None and dropping the entry) silently hides real models
    from any provider whose names don't match a hardcoded prefix.
    """
    lower = name.lower()
    if any(kw in lower for kw in ("tts-", "moderation")):
        return None
    if any(kw in lower for kw in _IMAGE_NAME_KEYWORDS):
        return "image"
    if "whisper" in lower:
        return "transcription"
    if "embedding" in lower:
        return "embedding"
    return "completion"


def _enrich_with_litellm_metadata(
    name: str, provider_type: str, mode_hint: str | None = None
) -> dict[str, Any] | None:
    """Look up `name` in litellm.model_cost and return an enriched capability
    dict, or None if the model should be hidden.

    This function owns presentation policy only: which models are surfaced
    (filter substrings, mode mapping) and which fields are extracted per mode.
    Which ``model_cost`` row a ``(name, provider_type)`` pair maps to is
    delegated to ``resolve_model_defaults`` so the runtime enrichment and
    ``/model-defaults/`` paths agree structurally. The one-shot cost backfill
    keeps an intentionally frozen copy of the same documented semantics.

    Returns None when the name matches a non-text filter substring or maps to
    a litellm mode we don't surface (tts, moderation, etc.).

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
    info = resolve_model_defaults(model_cost, name, provider_type)

    if info is None:
        chosen = mode_hint or _infer_mode_from_name(name)
        if chosen is None:
            return None
        return {"name": name, "mode": chosen}

    litellm_mode = info.get("mode", "")
    mode = LITELLM_MODE_TO_OUR_MODE.get(litellm_mode)
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
    elif mode == "image":
        enriched["cost_per_image"] = per_image_cost(info)
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

    def masked_api_key(self, provider: ModelProvider) -> str | None:
        """The provider's API key reduced to its last four characters, or None.

        The stored key is ciphertext when encryption is on, so it is decrypted
        here and only its last four characters leave this method. A key too
        short to hide, or one that cannot be decrypted, still reads as
        configured without revealing any of it.
        """
        stored_key = provider.credentials.get("api_key")
        if not stored_key:
            return None
        try:
            api_key = self.encryption.decrypt(stored_key)
        except (ValueError, EncryptionNotConfiguredException):
            return "****"
        return f"...{api_key[-4:]}" if len(api_key) > 4 else "****"

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
        from eneo.tenants.provider_field_config import get_field_definitions

        field_defs = get_field_definitions(provider_type)
        for field in field_defs:
            if field["required"]:
                source = credentials if field["in_"] == "credentials" else config
                value = source.get(field["name"])
                if not value or (isinstance(value, str) and not value.strip()):
                    raise BadRequestException(
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
        key_expires_on: date | None = None,
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
            key_expires_on=key_expires_on,
        )

        return await self.repository.create(provider)

    async def update(
        self,
        provider_id: UUID,
        name: Optional[str] = None,
        credentials: Optional[dict[str, Any]] = None,
        config: Optional[dict[str, Any]] = None,
        is_active: Optional[bool] = None,
        key_expires_on: date | None | Literal[Unchanged.UNCHANGED] = UNCHANGED,
    ) -> ModelProvider:
        """Update an existing provider.

        New credentials or a changed config clear the stored connection check:
        it describes settings the provider no longer has.
        """
        # Get existing provider
        provider = await self.repository.get_by_id(provider_id)
        connection_settings_changed = False

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
            connection_settings_changed = True

        if config is not None:
            # Merge with existing config so unchanged fields are preserved
            merged = {**provider.config, **config}
            connection_settings_changed |= merged != provider.config
            provider.config = merged

        if is_active is not None:
            provider.is_active = is_active

        if key_expires_on is not UNCHANGED:
            provider.key_expires_on = key_expires_on

        return await self.repository.update(
            provider, clear_connection_check=connection_settings_changed
        )

    async def delete(self, provider_id: UUID) -> None:
        """Delete a provider.

        Raises:
            BadRequestException: If the provider has models attached to it
        """
        # Check if provider has any models
        model_count = await self.repository.count_models_for_provider(provider_id)
        if model_count > 0:
            raise BadRequestException(
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
        For image models: skips validation (a real generation is billed and
        slow; a wrong name surfaces on first use through the provider error).
        """
        if model_type in ("transcription", "image"):
            return {
                "success": True,
                "message": f"Validation skipped for {model_type} models",
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
        header and the base URL — captured by ``models_list_request``, which
        also skips providers without a usable list (see there). Fields beyond
        ``id`` are pulled opportunistically through fallback chains in
        ``_normalize_live_model`` so providers with richer responses get more
        metadata, while minimal-shape providers still work.

        Returns entries with ``id``, optional ``display_name``, a
        ``created_at`` epoch-seconds value used to sort newest-first, and
        an optional ``mode_hint`` from provider-supplied capability fields.
        """
        import httpx

        request = models_list_request(provider_type, api_key, endpoint)
        if request is None:
            return []

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(request.url, headers=request.headers)
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
        endpoint = configured_endpoint(provider.config)

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

    async def check_connection(
        self, provider_id: UUID
    ) -> tuple[ModelProvider, ConnectionCheck]:
        """Call the provider with its stored credentials and store the result.

        The call lists the provider's models: authenticated, cheap and free of
        token costs. Returns the provider as stored afterwards (the result is
        dropped if its credentials changed during the call) and the result.

        Raises:
            ConnectionCheckNotSupportedException: No such call is known for
                this provider type without an endpoint.
        """
        provider = await self.repository.get_by_id(provider_id)
        provider_type = provider.provider_type.lower()
        api_key = str(
            self._decrypt_credentials(provider.credentials).get("api_key") or ""
        )
        request = connection_check_request(
            provider_type, api_key, configured_endpoint(provider.config)
        )
        if request is None:
            raise ConnectionCheckNotSupportedException(
                f"Connection checks are not supported for provider type "
                f"'{provider.provider_type}' without an endpoint."
            )

        if not api_key and is_field_required(provider_type, "api_key"):
            check = ConnectionCheck.failed(ConnectionCheckError.MISSING_CREDENTIALS)
        else:
            check = await probe_connection(
                request, provider_label=f"{provider.id} ({provider_type})"
            )
        return await self.repository.record_connection_check(provider, check), check
