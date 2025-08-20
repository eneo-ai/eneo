from typing import Any, Dict
from uuid import UUID

from fastapi import APIRouter, Depends

from intric.ai_models.completion_models.completion_model import (
    CompletionModelPublic,
    CompletionModelUpdateFlags,
)
from intric.ai_models.completion_models.completion_models_repo import (
    CompletionModelsRepository,
)
from intric.ai_models.embedding_models.embedding_model import (
    EmbeddingModelLegacy,
    EmbeddingModelPublicLegacy,
    EmbeddingModelUpdateFlags,
)
from intric.ai_models.embedding_models.embedding_models_repo import (
    AdminEmbeddingModelsService,
)
from intric.allowed_origins.allowed_origin_models import (
    AllowedOriginCreate,
    AllowedOriginInDB,
)
from intric.main.config import SETTINGS
from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.main.models import DeleteResponse, PaginatedResponse
from intric.server import protocol
from intric.server.dependencies.container import get_container
from intric.server.dependencies.get_repository import get_repository
from intric.server.protocol import responses
from intric.tenants.tenant import TenantBase, TenantInDB, TenantUpdatePublic
from intric.users.user import UserAddSuperAdmin, UserCreated, UserInDB, UserUpdatePublic
from intric.authentication import auth

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(auth.authenticate_super_api_key)])


@router.post(
    "/users/",
    response_model=UserCreated,
    responses=responses.get_responses([400, 401]),
)
async def register_new_user(
    new_user: UserAddSuperAdmin, container: Container = Depends(get_container())
):
    user_service = container.user_service()
    created_user, access_token, api_key = await user_service.register(new_user)

    return UserCreated(
        **created_user.model_dump(exclude={"api_key"}),
        access_token=access_token,
        api_key=api_key,
    )


@router.get("/users/", response_model=PaginatedResponse[UserInDB])
async def get_all_users(
    container: Container = Depends(get_container()),
):
    user_service = container.user_service()
    users_in_db = await user_service.get_all_users()

    return protocol.to_paginated_response(users_in_db)


@router.get("/users/{user_id}/", response_model=UserInDB)
async def get_user(
    user_id: UUID,
    container: Container = Depends(get_container()),
):
    user_service = container.user_service()
    return await user_service.get_user(user_id)


@router.delete("/users/{user_id}/", response_model=DeleteResponse)
async def delete_user(
    user_id: UUID,
    container: Container = Depends(get_container()),
):
    user_service = container.user_service()
    success = await user_service.delete_user(user_id)

    return DeleteResponse(success=success)


@router.post("/users/{user_id}/", response_model=UserInDB)
async def update_user(
    user_id: UUID,
    user_update: UserUpdatePublic,
    container: Container = Depends(get_container()),
):
    """Omitted fields are not updated."""
    user_service = container.user_service()
    return await user_service.update_user(user_id, user_update)


@router.post("/users/{user_id}/access-token/", include_in_schema=False)
async def get_access_token(user_id: UUID, container: Container = Depends(get_container())):
    user_repo = container.user_repo()
    auth_service = container.auth_service()

    user = await user_repo.get_user_by_id(user_id)

    return auth_service.create_access_token_for_user(user)


@router.get("/tenants/", response_model=PaginatedResponse[TenantInDB])
async def get_tenants(domain: str | None = None, container: Container = Depends(get_container())):
    tenant_service = container.tenant_service()

    tenants = await tenant_service.get_all_tenants(domain)

    return protocol.to_paginated_response(tenants)


@router.post(
    "/tenants/",
    response_model=TenantInDB,
    responses=responses.get_responses([400]),
)
async def create_tenant(tenant: TenantBase, container: Container = Depends(get_container())):
    tenant_service = container.tenant_service()

    return await tenant_service.create_tenant(tenant)


@router.post(
    "/tenants/{id}/",
    response_model=TenantInDB,
    responses=responses.get_responses([404]),
)
async def update_tenant(
    id: UUID,
    tenant: TenantUpdatePublic,
    container: Container = Depends(get_container()),
):
    tenant_service = container.tenant_service()

    return await tenant_service.update_tenant(tenant, id)


@router.delete(
    "/tenants/{id}/",
    response_model=TenantInDB,
    responses=responses.get_responses([404]),
)
async def delete_tenant_by_id(id: UUID, container: Container = Depends(get_container())):
    tenant_service = container.tenant_service()

    return await tenant_service.delete_tenant(id)


@router.get("/predefined-roles/")
async def get_predefined_roles(
    container: Container = Depends(get_container()),
):
    return await container.predefined_role_service().get_predefined_roles()


@router.post("/crawl-all-weekly-websites/")
async def crawl_all_weekly_websites(
    container: Container = Depends(get_container()),
):
    sysadmin_service = container.sysadmin_service()

    return await sysadmin_service.run_crawl_on_weekly_websites()


@router.get(
    "/embedding-models/",
    response_model=PaginatedResponse[EmbeddingModelLegacy],
    responses=responses.get_responses([404]),
)
async def get_embedding_models(
    embedding_model_repo: AdminEmbeddingModelsService = Depends(
        get_repository(AdminEmbeddingModelsService)
    ),
):
    models = await embedding_model_repo.get_models(with_deprecated=False)
    return protocol.to_paginated_response(models)


@router.get(
    "/completion-models/",
    response_model=PaginatedResponse[CompletionModelPublic],
    responses=responses.get_responses([404]),
)
async def get_completion_models(
    completion_model_repo: CompletionModelsRepository = Depends(
        get_repository(CompletionModelsRepository)
    ),
):
    models = await completion_model_repo.get_models(is_deprecated=False)
    return protocol.to_paginated_response(models)


@router.post(
    "/tenants/{id}/completion-models/{completion_model_id}/",
    response_model=CompletionModelPublic,
    responses=responses.get_responses([404]),
)
async def enable_completion_model(
    id: UUID,
    completion_model_id: UUID,
    data: CompletionModelUpdateFlags,
    completion_model_repo: CompletionModelsRepository = Depends(
        get_repository(CompletionModelsRepository)
    ),
):
    await completion_model_repo.enable_completion_model(
        is_org_enabled=data.is_org_enabled,
        completion_model_id=completion_model_id,
        tenant_id=id,
    )

    return await completion_model_repo.get_model(completion_model_id, tenant_id=id)


@router.post(
    "/tenants/{id}/embedding-models/{embedding_model_id}/",
    response_model=EmbeddingModelPublicLegacy,
    responses=responses.get_responses([404]),
)
async def enable_embedding_model(
    id: UUID,
    embedding_model_id: UUID,
    data: EmbeddingModelUpdateFlags,
    embedding_model_repo: AdminEmbeddingModelsService = Depends(
        get_repository(AdminEmbeddingModelsService)
    ),
):
    await embedding_model_repo.enable_embedding_model(
        is_org_enabled=data.is_org_enabled,
        embedding_model_id=embedding_model_id,
        tenant_id=id,
    )

    return await embedding_model_repo.get_model(embedding_model_id, tenant_id=id)


@router.post("/allowed-origins/", response_model=AllowedOriginInDB)
async def add_origin(
    origin: AllowedOriginCreate,
    container: Container = Depends(get_container()),
):
    allowed_origin_repo = container.allowed_origin_repo()
    return await allowed_origin_repo.add_origin(origin=origin.url, tenant_id=origin.tenant_id)


@router.get("/allowed-origins/", response_model=PaginatedResponse[AllowedOriginInDB])
async def get_origins(
    tenant_id: UUID | None = None,
    container: Container = Depends(get_container()),
):
    allowed_origin_repo = container.allowed_origin_repo()

    if tenant_id is not None:
        allowed_origins = await allowed_origin_repo.get_by_tenant(tenant_id)
    else:
        allowed_origins = await allowed_origin_repo.get_all()

    return protocol.to_paginated_response(allowed_origins)


@router.delete("/allowed-origins/{id}/", status_code=204)
async def delete_origin(
    id: UUID,
    container: Container = Depends(get_container()),
):
    allowed_origin_repo = container.allowed_origin_repo()
    await allowed_origin_repo.delete(id)


@router.get("/config/health", response_model=Dict[str, Any])
async def get_config_health():
    """
    Get configuration health status for administrative monitoring.
    
    This endpoint provides a comprehensive view of the application configuration
    status, including validation results and feature status. Secrets are masked
    for security purposes.
    
    Returns:
        Dict containing configuration validation results and feature status
    """
    # Run configuration validation
    config_status = SETTINGS.check()
    
    # Get configuration summary with masked secrets
    summary = SETTINGS.get_summary(mask_secrets=True)
    
    # Enhanced health status with new structure
    health_status = {
        "status": "healthy" if not config_status["errors"] else ("degraded" if config_status["warnings"] else "unhealthy"),
        "config_hash": config_status["config_hash"],
        "timestamp": config_status["timestamp"],
        "validation": {
            "errors": config_status["errors"],
            "warnings": config_status["warnings"],
            "unknown_vars": config_status["unknown_vars"],
            "error_count": len(config_status["errors"]),
            "warning_count": len(config_status["warnings"]),
            "unknown_count": len(config_status["unknown_vars"])
        },
        "features": {
            "ai_models": {
                name: {"enabled": bool(status not in ["Not set", "Disabled"]), 
                       "reason": "API key configured" if status not in ["Not set", "Disabled"] else "API key not set"}
                for name, status in summary["ai_models"].items() if status != "Disabled"
            },
            "integrations": {
                "crawling": {"enabled": SETTINGS.using_crawl},
                "image_generation": {"enabled": SETTINGS.using_image_generation},
                "access_management": {"enabled": SETTINGS.using_access_management},
                "iam": {"enabled": SETTINGS.using_iam},
                "confluence": {"enabled": bool(SETTINGS.confluence_client_id)},
                "sharepoint": {"enabled": bool(SETTINGS.sharepoint_client_id)}
            },
            "auth_providers": {
                "mobilityguard": {
                    "enabled": bool(SETTINGS.mobilityguard_client_id and SETTINGS.mobilityguard_discovery_endpoint),
                    "configured": summary["auth_providers"]["mobilityguard"]
                }
            }
        },
        "summary": {
            "total_models": len([k for k, v in summary['ai_models'].items() if v != "Disabled"]),
            "configured_models": len([k for k, v in summary['ai_models'].items() if v not in ["Not set", "Disabled"]]),
            "enabled_features": len([k for k, v in summary['features'].items() if v]),
            "total_features": len(summary['features'])
        },
        "environment": {
            "app_version": summary["app_version"],
            "environment_type": summary["environment"],
            "development_mode": SETTINGS.dev,
            "testing_mode": SETTINGS.testing
        }
    }
    
    return health_status
