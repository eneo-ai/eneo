import re
from collections import defaultdict
from datetime import date
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from typing_extensions import TypedDict

from intric.authentication.auth_dependencies import get_current_active_user
from intric.database.database import AsyncSession, get_session_with_transaction
from intric.main.config import get_settings
from intric.model_providers.domain.model_defaults_lookup import resolve_model_defaults
from intric.model_providers.domain.model_provider_service import ModelProviderService
from intric.model_providers.infrastructure.model_provider_repository import (
    ModelProviderRepository,
)
from intric.model_providers.presentation.model_provider_models import (
    FavoriteProvidersUpdate,
    ModelProviderCreate,
    ModelProviderPublic,
    ModelProviderUpdate,
    ValidateModelRequest,
)
from intric.roles.permissions import Permission, validate_permission
from intric.server.protocol import responses
from intric.settings.encryption_service import EncryptionService
from intric.tenants.provider_field_config import (
    DEFAULT_FIELDS,
    PROVIDER_FIELD_DEFINITIONS,
    FieldDefinition,
    get_canonical_provider_type,
    get_field_definitions,
)
from intric.tenants.tenant_repo import TenantRepository
from intric.users.user import UserInDB

router = APIRouter()

CurrentUser = Annotated[UserInDB, Depends(get_current_active_user)]
SessionDep = Annotated[AsyncSession, Depends(get_session_with_transaction)]
SerializedField = TypedDict(
    "SerializedField",
    {"name": str, "required": bool, "secret": bool, "in": str},
)


class ModelCostInfo(TypedDict, total=False):
    litellm_provider: str
    mode: str
    deprecation_date: str
    max_input_tokens: int | None
    max_output_tokens: int | None
    output_vector_size: int | None
    supports_vision: bool
    supports_function_calling: bool
    supports_reasoning: bool
    # Cost fields. Token-based for chat/completion/embedding; per-second for
    # most audio_transcription entries (Whisper et al.).
    input_cost_per_token: float | None
    output_cost_per_token: float | None
    input_cost_per_second: float | None
    output_cost_per_second: float | None


class ModelCapabilityBase(TypedDict):
    name: str


class ModelCapability(ModelCapabilityBase, total=False):
    max_input_tokens: int | None
    max_output_tokens: int | None
    output_vector_size: int | None
    supports_vision: bool
    supports_function_calling: bool
    supports_reasoning: bool
    # Indicative pricing — surfaced so that picking a suggestion in the wizard
    # populates the cost fields without a second `/model-defaults/` round-trip.
    # Token-priced for completion + embedding; per-minute for transcription
    # (derived from LiteLLM's per-second value × 60).
    input_cost_per_token: float | None
    output_cost_per_token: float | None
    cost_per_minute: float | None


class ProviderCapabilities(TypedDict):
    modes: list[str]
    models: dict[str, list[ModelCapability]]
    fields: list[SerializedField]


def serialize_fields(fields: list[FieldDefinition]) -> list[SerializedField]:
    return [
        {
            "name": field["name"],
            "required": field["required"],
            "secret": field["secret"],
            "in": field["in_"],
        }
        for field in fields
    ]


def get_model_provider_service(
    user: CurrentUser,
    session: SessionDep,
) -> ModelProviderService:
    """Dependency for getting the model provider service."""
    settings = get_settings()
    encryption = EncryptionService(settings)
    repository = ModelProviderRepository(session, user.tenant_id)
    return ModelProviderService(repository, encryption)


ServiceDep = Annotated[ModelProviderService, Depends(get_model_provider_service)]


@router.get(
    "/",
    response_model=list[ModelProviderPublic],
)
async def list_providers(
    user: CurrentUser,
    service: ServiceDep,
) -> list[ModelProviderPublic]:
    """List all model providers for the tenant."""
    validate_permission(user, Permission.ADMIN)
    providers = await service.get_all()
    return [ModelProviderPublic(**provider.to_dict()) for provider in providers]


@router.get(
    "/capabilities/",
)
async def get_provider_capabilities(
    _user: CurrentUser,
) -> dict[str, object]:
    """Get supported model types and top models per provider type from LiteLLM.

    Returns a structured response with:
    - providers: dict of canonical provider types, each with modes, models, and fields
    - default_fields: fallback field definitions for providers without custom fields
    """
    import litellm

    # Mode mapping: LiteLLM mode -> our model type
    mode_map = {
        "chat": "completion",
        "completion": "completion",
        "embedding": "embedding",
        "audio_transcription": "transcription",
    }

    # Date extraction for sorting by release date (newest first).
    # LiteLLM has no release_date field, so we extract from model names.
    # Supports: YYYY-MM-DD (OpenAI), YYYYMMDD (Anthropic), @YYYYMMDD (Vertex)
    _date_dashed = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
    _date_compact = re.compile(r"(?:@|-)(\d{8})(?:\D|$)|(\d{8})$")

    def _extract_model_date(name: str) -> str:
        """Extract date from model name, normalized to YYYYMMDD for sorting."""
        # YYYY-MM-DD (e.g. gpt-4o-2024-08-06)
        m = _date_dashed.search(name)
        if m:
            return f"{m.group(1)}{m.group(2)}{m.group(3)}"
        # YYYYMMDD (e.g. claude-opus-4-6-20260205, vertex @20241022)
        m = _date_compact.search(name)
        if m:
            return m.group(1) or m.group(2)
        return "00000000"

    # Collect all models per provider per mode with metadata
    model_cost = cast(dict[str, ModelCostInfo], getattr(litellm, "model_cost"))
    raw: dict[str, dict[str, dict[str, ModelCapability]]] = defaultdict(
        lambda: defaultdict(dict)
    )

    today = date.today().isoformat()

    for model_key, info in model_cost.items():
        raw_provider = info.get("litellm_provider", "")
        litellm_mode = info.get("mode", "")
        mode = mode_map.get(litellm_mode)

        # Skip fine-tuned model templates
        if model_key.startswith("ft:"):
            continue

        # Skip deprecated models
        dep = info.get("deprecation_date")
        if dep and dep <= today:
            continue

        # Skip *-latest aliases (the concrete dated versions are more useful)
        if model_key.endswith("-latest"):
            continue

        # Skip non-standard model types that aren't useful for text chat/embedding
        model_lower = model_key.lower()
        if model_lower.endswith("/container"):
            continue
        if any(
            kw in model_lower
            for kw in (
                "realtime",
                "-audio-",
                "gpt-audio",
                "search-preview",
                "search-api",
                "-diarize",
            )
        ):
            continue

        # Map to canonical provider type (e.g. "vllm" -> "hosted_vllm")
        provider = get_canonical_provider_type(raw_provider) if raw_provider else ""

        if provider and mode and model_key not in raw[provider][mode]:
            model_info: ModelCapability = {"name": model_key}
            if mode == "completion":
                model_info["max_input_tokens"] = info.get("max_input_tokens")
                model_info["max_output_tokens"] = info.get("max_output_tokens")
                model_info["supports_vision"] = info.get("supports_vision", False)
                model_info["supports_function_calling"] = info.get(
                    "supports_function_calling", False
                )
                model_info["supports_reasoning"] = info.get("supports_reasoning", False)
                model_info["input_cost_per_token"] = info.get("input_cost_per_token")
                model_info["output_cost_per_token"] = info.get("output_cost_per_token")
            elif mode == "embedding":
                model_info["max_input_tokens"] = info.get("max_input_tokens")
                model_info["output_vector_size"] = info.get("output_vector_size")
                model_info["input_cost_per_token"] = info.get("input_cost_per_token")
                model_info["output_cost_per_token"] = info.get("output_cost_per_token")
            elif mode == "transcription":
                # LiteLLM stores transcription rates per-second on most entries
                # (Whisper, Deepgram). Expose per-minute so the form shows a
                # human-readable number directly.
                input_per_second = info.get("input_cost_per_second")
                if isinstance(input_per_second, (int, float)):
                    model_info["cost_per_minute"] = input_per_second * 60
            raw[provider][mode][model_key] = model_info

    # Build response sorted by release date (newest first)
    providers: dict[str, ProviderCapabilities] = {}
    for provider, modes in raw.items():
        provider_data: ProviderCapabilities = {
            "modes": sorted(modes.keys()),
            "models": {},
            "fields": serialize_fields(get_field_definitions(provider)),
        }
        for mode, models_dict in modes.items():
            provider_data["models"][mode] = sorted(
                models_dict.values(),
                key=lambda m: _extract_model_date(m["name"]),
                reverse=True,
            )
        providers[provider] = provider_data

    # Ensure providers with custom field definitions are always present
    # (e.g. hosted_vllm, which is self-hosted and has no static models in LiteLLM)
    for provider_type in PROVIDER_FIELD_DEFINITIONS:
        if provider_type not in providers:
            providers[provider_type] = {
                # Self-hosted providers can host any model type
                "modes": sorted(set(mode_map.values())),
                "models": {},
                "fields": serialize_fields(get_field_definitions(provider_type)),
            }

    return {
        "providers": providers,
        "default_fields": serialize_fields(DEFAULT_FIELDS),
    }


@router.get("/favorites/")
async def get_favorite_providers(
    user: CurrentUser,
    session: SessionDep,
) -> dict[str, list[str]]:
    """Get the tenant's favorite provider types."""
    repo = TenantRepository(session)
    tenant = await repo.get(user.tenant_id)
    assert tenant is not None
    return {"providers": tenant.favorite_providers}


@router.put("/favorites/")
async def set_favorite_providers(
    body: FavoriteProvidersUpdate,
    user: CurrentUser,
    session: SessionDep,
) -> dict[str, list[str]]:
    """Set the tenant's favorite provider types."""
    repo = TenantRepository(session)
    await repo.update_favorite_providers(user.tenant_id, body.providers)
    return {"providers": body.providers}


@router.get(
    "/model-defaults/",
)
async def get_model_defaults(
    model_name: str,
    _user: CurrentUser,
    provider_type: str | None = Query(
        default=None,
        description=(
            "Canonical provider type the model belongs to (e.g. 'openai', "
            "'azure'). When provided, '{provider_type}/{model_name}' is "
            "preferred over the bare entry so Azure-served gpt-4o picks up "
            "azure/gpt-4o prices instead of openai/gpt-4o."
        ),
    ),
) -> dict[str, object]:
    """Look up recommended default values for a model from LiteLLM's model_cost database."""
    import litellm

    model_cost = cast(dict[str, ModelCostInfo], getattr(litellm, "model_cost"))
    info = resolve_model_defaults(
        cast(dict[str, dict[str, Any]], model_cost), model_name, provider_type
    )

    if info is None:
        return {"found": False}

    # Cost fields differ by mode. Frontend asks for both shapes; we surface
    # whichever the model actually has so the wizard/edit dialog can write the
    # right column. cost_per_minute is derived from per-second when present.
    input_cost_per_token = info.get("input_cost_per_token")
    output_cost_per_token = info.get("output_cost_per_token")
    input_per_second = info.get("input_cost_per_second")
    cost_per_minute = (
        input_per_second * 60 if isinstance(input_per_second, (int, float)) else None
    )

    return {
        "found": True,
        "max_input_tokens": info.get("max_input_tokens"),
        "max_output_tokens": info.get("max_output_tokens"),
        "supports_vision": info.get("supports_vision", False),
        "supports_function_calling": info.get("supports_function_calling", False),
        "supports_reasoning": info.get("supports_reasoning", False),
        "input_cost_per_token": input_cost_per_token,
        "output_cost_per_token": output_cost_per_token,
        "cost_per_minute": cost_per_minute,
    }


@router.get(
    "/{provider_id}/",
    response_model=ModelProviderPublic,
    responses=responses.get_responses([404]),
)
async def get_provider(
    provider_id: UUID,
    user: CurrentUser,
    service: ServiceDep,
) -> ModelProviderPublic:
    """Get a specific model provider."""
    validate_permission(user, Permission.ADMIN)
    provider = await service.get_by_id(provider_id)
    return ModelProviderPublic(**provider.to_dict())


@router.post(
    "/",
    response_model=ModelProviderPublic,
    responses=responses.get_responses([409]),
)
async def create_provider(
    data: ModelProviderCreate,
    user: CurrentUser,
    service: ServiceDep,
) -> ModelProviderPublic:
    """Create a new model provider."""
    validate_permission(user, Permission.ADMIN)
    provider = await service.create(
        tenant_id=user.tenant_id,
        name=data.name,
        provider_type=data.provider_type,
        credentials=data.credentials,
        config=data.config,
        is_active=data.is_active,
    )
    return ModelProviderPublic(**provider.to_dict())


@router.put(
    "/{provider_id}/",
    response_model=ModelProviderPublic,
    responses=responses.get_responses([404, 409]),
)
async def update_provider(
    provider_id: UUID,
    data: ModelProviderUpdate,
    user: CurrentUser,
    service: ServiceDep,
) -> ModelProviderPublic:
    """Update an existing model provider."""
    validate_permission(user, Permission.ADMIN)
    provider = await service.update(
        provider_id=provider_id,
        name=data.name,
        credentials=data.credentials,
        config=data.config,
        is_active=data.is_active,
    )
    return ModelProviderPublic(**provider.to_dict())


@router.get(
    "/{provider_id}/models/",
    responses=responses.get_responses([404]),
)
async def list_provider_models(
    provider_id: UUID,
    service: ServiceDep,
    mode: Annotated[
        Literal["completion", "embedding", "transcription"] | None,
        Query(description="Filter response to a single mode."),
    ] = None,
) -> list[dict[str, Any]]:
    """List available models from the provider's API using its credentials.

    Each entry has at least ``name`` and ``mode``. Completion entries also
    include ``max_input_tokens``, ``max_output_tokens`` and ``supports_*``
    flags; embedding entries include ``max_input_tokens`` and
    ``output_vector_size``. When ``mode`` is supplied the server returns
    only matching entries — consumers don't need to filter client-side.
    """
    return await service.list_available_models(provider_id, mode=mode)


@router.post(
    "/{provider_id}/test/",
    responses=responses.get_responses([404]),
)
async def test_provider(
    provider_id: UUID,
    service: ServiceDep,
) -> dict[str, Any]:
    """Test connectivity to a model provider."""
    return await service.test_connection(provider_id)


@router.post(
    "/{provider_id}/validate-model/",
    responses=responses.get_responses([404]),
)
async def validate_model(
    provider_id: UUID,
    body: ValidateModelRequest,
    service: ServiceDep,
) -> dict[str, Any]:
    """Validate that a model works with this provider by making a minimal API call."""
    return await service.validate_model(provider_id, body.model_name, body.model_type)


@router.delete(
    "/{provider_id}/",
    responses=responses.get_responses([404]),
)
async def delete_provider(
    provider_id: UUID,
    user: CurrentUser,
    service: ServiceDep,
) -> dict[str, str]:
    """Delete a model provider.

    Will fail if the provider has models attached to it.
    """
    validate_permission(user, Permission.ADMIN)
    await service.delete(provider_id)
    return {"message": "Provider deleted successfully"}
