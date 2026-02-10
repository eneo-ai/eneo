from fastapi import APIRouter, Depends

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
from intric.settings.settings import GetModelsResponse, SettingsPublic, ToggleSettingUpdate

logger = get_logger(__name__)

router = APIRouter()
settings_admin_router = APIRouter()


@router.get("/", response_model=SettingsPublic)
async def get_settings(
    service: SettingService = Depends(
        settings_factory.get_settings_service_allowing_read_only_key
    ),
):
    return await service.get_settings()


@settings_admin_router.post("/", response_model=SettingsPublic)
async def upsert_settings(
    settings: SettingsPublic,
    container: Container = Depends(get_container(with_user=True)),
):
    """Omitted fields are not updated."""
    validate_permission(container.user(), Permission.ADMIN)
    service = container.settings_service()
    return await service.update_settings(settings)


@router.get("/models/", response_model=GetModelsResponse)
async def get_models(
    container: Container = Depends(get_container(with_user=True)),
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
    container: Container = Depends(get_container(with_user=True)),
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
    container: Container = Depends(get_container(with_user=True)),
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
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.settings_service()
    return await service.update_provisioning_setting(enabled=data.enabled)


@settings_admin_router.patch(
    "/scope-enforcement",
    response_model=SettingsPublic,
    summary="Toggle API key scope enforcement",
    description="""
Toggle API key scope enforcement for your tenant.

**Admin Only:** Requires admin permissions.

**Behavior:**
- Updates the `api_key_scope_enforcement` feature flag for your tenant
- When enabled: API keys are restricted to resources within their configured scope
- When disabled: All API keys can access resources beyond their configured scope
- Disabling scope enforcement also disables strict mode for consistency
- Change takes effect immediately for all API key requests
    """,
)
async def update_scope_enforcement_setting(
    data: ToggleSettingUpdate,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.settings_service()
    return await service.update_scope_enforcement_setting(enabled=data.enabled)


@settings_admin_router.patch(
    "/strict-mode",
    response_model=SettingsPublic,
    summary="Toggle API key strict mode",
    description="""
Toggle API key strict mode for your tenant.

**Admin Only:** Requires admin permissions.

**Behavior:**
- Updates the `api_key_strict_mode` feature flag for your tenant
- When enabled: scoped API keys are enforced with strict fail-closed semantics
- When disabled: default scope enforcement behavior applies
- Enabling strict mode requires `api_key_scope_enforcement` to be enabled
- Change takes effect immediately for API key requests
    """,
)
async def update_strict_mode_setting(
    data: ToggleSettingUpdate,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.settings_service()
    return await service.update_strict_mode_setting(enabled=data.enabled)
