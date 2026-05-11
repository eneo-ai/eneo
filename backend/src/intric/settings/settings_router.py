from typing import Annotated, Mapping, cast

from fastapi import APIRouter, Depends

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.authentication import auth_dependencies
from intric.files.audio import AudioMimeTypes
from intric.files.image import ImageMimeTypes
from intric.files.text import TextMimeTypes
from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.main.models import PaginatedResponse
from intric.roles.permissions import Permission, validate_permission
from intric.server.dependencies.container import get_container
from intric.server.protocol import to_paginated_response
from intric.settings import settings_factory
from intric.settings.setting_service import SettingService
from intric.settings.settings import (
    GetModelsResponse,
    SettingsPublic,
    ToggleSettingUpdate,
)
from intric.tenants.crawler_settings_models import (
    CrawlerSettingsResponse,
    CrawlerSettingsSelfServiceUpdate,
)

logger = get_logger(__name__)

router = APIRouter()
settings_admin_router = APIRouter()


@router.get("/", response_model=SettingsPublic)
async def get_settings(
    service: Annotated[
        SettingService,
        Depends(settings_factory.get_settings_service_allowing_read_only_key),
    ],
):
    return await service.get_settings()


@settings_admin_router.post("/", response_model=SettingsPublic)
async def upsert_settings(
    settings: SettingsPublic,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """Omitted fields are not updated."""
    validate_permission(container.user(), Permission.ADMIN)
    service = container.settings_service()
    return await service.update_settings(settings)


@router.get("/models/", response_model=GetModelsResponse)
async def get_models(
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """
    From the response:
        - use the `id` field as values for `completion_model`
        - use the `id` field as values for `embedding_model`

    in creating and updating `Assistants` and `Services`.
    """
    service = container.settings_service()
    completion_models = await service.get_available_completion_models()
    embedding_models = await service.get_available_embedding_models()

    return GetModelsResponse(
        completion_models=completion_models, embedding_models=embedding_models
    )


@router.get(
    "/formats/",
    response_model=PaginatedResponse[str],
    dependencies=[Depends(auth_dependencies.get_current_active_user)],
)
def get_formats():
    return to_paginated_response(
        TextMimeTypes.values() + AudioMimeTypes.values() + ImageMimeTypes.values()
    )


@settings_admin_router.patch(
    "/templates",
    response_model=SettingsPublic,
    summary="Toggle template feature",
    description="""
Enable or disable the template management feature for your tenant.

**Admin Only:** Requires admin permissions.

**Behavior:**
- Updates the `using_templates` feature flag for your tenant
- When disabled: Template gallery returns empty list (not error)
- When enabled: Users can see and use tenant templates
- Change takes effect immediately (no reload required)

**Example Request:**
```json
{
  "enabled": true
}
```

**Example Response:**
```json
{
  "chatbot_widget": {},
  "using_templates": true
}
```
    """,
)
async def update_template_setting(
    data: ToggleSettingUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """
    Toggle template feature for tenant.

    Enables or disables the template management feature for the entire tenant.
    Only admin users can modify this setting.
    """
    service = container.settings_service()
    return await service.update_template_setting(enabled=data.enabled)


@settings_admin_router.patch(
    "/audit-logging",
    response_model=SettingsPublic,
    summary="Toggle global audit logging",
    description="""
Enable or disable global audit logging for your tenant.

**Admin Only:** Requires admin permissions.

**Behavior:**
- Updates the `audit_logging_enabled` feature flag for your tenant
- When disabled: No audit logs are created for any action (global kill switch)
- When enabled: Audit logging resumes with category and action-level filtering
- This is independent from category/action configuration
- Change takes effect immediately for all workers

**Example Request:**
```json
{
  "enabled": false
}
```

**Example Response:**
```json
{
  "chatbot_widget": {},
  "audit_logging_enabled": false,
  "using_templates": true
}
```
    """,
)
async def update_audit_logging_setting(
    data: ToggleSettingUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """
    Toggle global audit logging for tenant.

    Enables or disables all audit logging for the entire tenant (global kill switch).
    Only admin users can modify this setting.
    """
    service = container.settings_service()
    return await service.update_audit_logging_setting(enabled=data.enabled)


@settings_admin_router.patch(
    "/provisioning",
    response_model=SettingsPublic,
    summary="Toggle JIT user provisioning",
    description="""
Enable or disable JIT (Just-In-Time) user provisioning for your tenant.

**Admin Only:** Requires admin permissions.

**Behavior:**
- When enabled: Users are automatically created on first SSO login
- When disabled: Only pre-existing users can log in via SSO
- New users get the "User" role by default
- Change takes effect immediately for all SSO logins

**Example Request:**
```json
{
  "enabled": true
}
```

**Example Response:**
```json
{
  "chatbot_widget": {},
  "using_templates": true,
  "audit_logging_enabled": true,
  "provisioning": true
}
```
    """,
)
async def update_provisioning_setting(
    data: ToggleSettingUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.settings_service()
    return await service.update_provisioning_setting(enabled=data.enabled)


@settings_admin_router.patch(
    "/api-key-expiry-notifications",
    response_model=SettingsPublic,
    summary="Toggle API key expiry notifications",
    description="""
Toggle API key expiry notifications for your tenant.

**Admin Only:** Requires admin permissions.

**Behavior:**
- Updates the `api_key_expiry_notifications` feature flag for your tenant
- When enabled: API key expiry notification surfaces are active
- When disabled: API key expiry notifications are suppressed
- Change takes effect immediately
    """,
)
async def update_api_key_expiry_notifications_setting(
    data: ToggleSettingUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.settings_service()
    return await service.update_api_key_expiry_notifications_setting(
        enabled=data.enabled
    )


@settings_admin_router.get(
    "/crawler",
    response_model=CrawlerSettingsResponse,
    summary="Get crawler settings",
)
async def get_current_tenant_crawler_settings(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> CrawlerSettingsResponse:
    validate_permission(container.user(), Permission.ADMIN)
    tenant_service = container.tenant_service()
    result = await tenant_service.get_crawler_settings(
        tenant_id=container.user().tenant_id
    )
    return CrawlerSettingsResponse.model_validate(result)


@settings_admin_router.patch(
    "/crawler",
    response_model=CrawlerSettingsResponse,
    summary="Update crawler settings",
)
async def update_current_tenant_crawler_settings(
    data: CrawlerSettingsSelfServiceUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> CrawlerSettingsResponse:
    validate_permission(container.user(), Permission.ADMIN)
    user = container.user()
    tenant_service = container.tenant_service()
    updates = data.model_dump(exclude_none=True)

    if not updates:
        result = await tenant_service.get_crawler_settings(tenant_id=user.tenant_id)
        return CrawlerSettingsResponse.model_validate(result)

    before = await tenant_service.get_crawler_settings(tenant_id=user.tenant_id)
    before_settings = cast(Mapping[str, object], before["settings"])
    result = await tenant_service.update_crawler_settings(
        tenant_id=user.tenant_id,
        settings=updates,
    )
    after_settings = cast(Mapping[str, object], result["settings"])

    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.TENANT_SETTINGS_UPDATED,
        entity_type=EntityType.TENANT_SETTINGS,
        entity_id=user.tenant_id,
        description="Updated crawler settings",
        metadata={
            "setting": "crawler_settings",
            "changes": {
                key: {
                    "old": before_settings.get(key),
                    "new": after_settings.get(key),
                }
                for key in updates
            },
        },
    )

    return CrawlerSettingsResponse.model_validate(result)
