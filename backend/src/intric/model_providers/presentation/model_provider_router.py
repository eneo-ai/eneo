from uuid import UUID

from fastapi import APIRouter, Depends

from intric.authentication.auth_dependencies import get_current_active_user
from intric.roles.permissions import Permission, validate_permission
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
    user: UserInDB = Depends(get_current_active_user),
    service: ModelProviderService = Depends(get_model_provider_service),
):
    """Update an existing model provider."""
    validate_permission(user, Permission.ADMIN)
    provider = await service.update(
        provider_id=provider_id,
        name=data.name,
        provider_type=data.provider_type,
        credentials=data.credentials,
        config=data.config,
        is_active=data.is_active,
    )
    return ModelProviderPublic(**provider.to_dict())


@router.delete(
    "/{provider_id}/",
    responses=responses.get_responses([404]),
)
async def delete_provider(
    provider_id: UUID,
    user: UserInDB = Depends(get_current_active_user),
    service: ModelProviderService = Depends(get_model_provider_service),
):
    """Delete a model provider.

    Will fail if the provider has models attached to it.
    """
    validate_permission(user, Permission.ADMIN)
    await service.delete(provider_id)
    return {"message": "Provider deleted successfully"}
