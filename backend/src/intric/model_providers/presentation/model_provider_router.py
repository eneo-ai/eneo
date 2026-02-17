from uuid import UUID

from fastapi import APIRouter, Depends

from intric.authentication.auth_dependencies import get_current_active_user
from intric.database.database import AsyncSession, get_session_with_transaction
from intric.main.config import get_settings
from intric.model_providers.domain.model_provider_service import ModelProviderService
from intric.model_providers.infrastructure.model_provider_repository import (
    ModelProviderRepository,
)
from intric.model_providers.presentation.model_provider_models import (
    ModelProviderCreate,
    ModelProviderPublic,
    ModelProviderUpdate,
    ValidateModelRequest,
)
from intric.server.protocol import responses
from intric.settings.encryption_service import EncryptionService
from intric.users.user import UserInDB

router = APIRouter()


def get_model_provider_service(
    user: UserInDB = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session_with_transaction),
) -> ModelProviderService:
    """Dependency for getting the model provider service."""
    settings = get_settings()
    encryption = EncryptionService(settings)
    repository = ModelProviderRepository(session, user.tenant_id)
    return ModelProviderService(repository, encryption)


@router.get(
    "/",
    response_model=list[ModelProviderPublic],
)
async def list_providers(
    service: ModelProviderService = Depends(get_model_provider_service),
):
    """List all model providers for the tenant."""
    providers = await service.get_all()
    return [ModelProviderPublic(**provider.to_dict()) for provider in providers]


@router.get(
    "/capabilities/",
)
async def get_provider_capabilities(
    _user: UserInDB = Depends(get_current_active_user),
):
    """Get supported model types and top models per provider type from LiteLLM."""
    import litellm
    from collections import defaultdict

    # Mode mapping: LiteLLM mode -> our model type
    mode_map = {
        "chat": "completion",
        "completion": "completion",
        "embedding": "embedding",
        "audio_transcription": "transcription",
    }

    # Collect all models per provider per mode with metadata
    raw: dict[str, dict[str, dict[str, dict]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    from datetime import date

    today = date.today().isoformat()

    for model_key, info in litellm.model_cost.items():
        provider = info.get("litellm_provider", "")
        litellm_mode = info.get("mode", "")
        mode = mode_map.get(litellm_mode)

        # Skip fine-tuned model templates
        if model_key.startswith("ft:"):
            continue

        # Skip deprecated models
        dep = info.get("deprecation_date")
        if dep and dep <= today:
            continue

        if provider and mode and model_key not in raw[provider][mode]:
            model_info: dict = {"name": model_key}
            if mode == "completion":
                model_info["max_input_tokens"] = info.get("max_input_tokens")
                model_info["max_output_tokens"] = info.get("max_output_tokens")
                model_info["supports_vision"] = info.get("supports_vision", False)
                model_info["supports_function_calling"] = info.get(
                    "supports_function_calling", False
                )
                model_info["supports_reasoning"] = info.get(
                    "supports_reasoning", False
                )
            elif mode == "embedding":
                model_info["max_input_tokens"] = info.get("max_input_tokens")
                model_info["output_vector_size"] = info.get("output_vector_size")
            raw[provider][mode][model_key] = model_info

    # Build response sorted alphabetically
    result = {}
    for provider, modes in raw.items():
        provider_data: dict = {"modes": sorted(modes.keys()), "models": {}}
        for mode, models_dict in modes.items():
            provider_data["models"][mode] = sorted(
                models_dict.values(), key=lambda m: m["name"]
            )
        result[provider] = provider_data

    return result


@router.get(
    "/{provider_id}/",
    response_model=ModelProviderPublic,
    responses=responses.get_responses([404]),
)
async def get_provider(
    provider_id: UUID,
    service: ModelProviderService = Depends(get_model_provider_service),
):
    """Get a specific model provider."""
    provider = await service.get_by_id(provider_id)
    return ModelProviderPublic(**provider.to_dict())


@router.post(
    "/",
    response_model=ModelProviderPublic,
    responses=responses.get_responses([409]),
)
async def create_provider(
    data: ModelProviderCreate,
    user: UserInDB = Depends(get_current_active_user),
    service: ModelProviderService = Depends(get_model_provider_service),
):
    """Create a new model provider."""
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
    service: ModelProviderService = Depends(get_model_provider_service),
):
    """Update an existing model provider."""
    provider = await service.update(
        provider_id=provider_id,
        name=data.name,
        provider_type=data.provider_type,
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
    service: ModelProviderService = Depends(get_model_provider_service),
):
    """List available models/deployments from the provider's API using its credentials."""
    return await service.list_available_models(provider_id)


@router.post(
    "/{provider_id}/test/",
    responses=responses.get_responses([404]),
)
async def test_provider(
    provider_id: UUID,
    service: ModelProviderService = Depends(get_model_provider_service),
):
    """Test connectivity to a model provider."""
    return await service.test_connection(provider_id)


@router.post(
    "/{provider_id}/validate-model/",
    responses=responses.get_responses([404]),
)
async def validate_model(
    provider_id: UUID,
    body: ValidateModelRequest,
    service: ModelProviderService = Depends(get_model_provider_service),
):
    """Validate that a model works with this provider by making a minimal API call."""
    return await service.validate_model(provider_id, body.model_name, body.model_type)


@router.delete(
    "/{provider_id}/",
    responses=responses.get_responses([404]),
)
async def delete_provider(
    provider_id: UUID,
    service: ModelProviderService = Depends(get_model_provider_service),
):
    """Delete a model provider.

    Will fail if the provider has models attached to it.
    """
    await service.delete(provider_id)
    return {"message": "Provider deleted successfully"}
