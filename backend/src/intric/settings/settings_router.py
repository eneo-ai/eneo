from typing import Annotated, Protocol, cast

from fastapi import APIRouter, Depends

from intric.authentication import auth_dependencies
from intric.files.mime_support import supported_mimes
from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.main.models import PaginatedResponse
from intric.roles.permissions import Permission, validate_permission
from intric.server.dependencies.container import get_container
from intric.server.protocol import to_paginated_response
from intric.settings import settings_factory
from intric.settings.setting_service import SettingService
from intric.settings.settings import (
    AIBuilderBudgetSettingsPublic,
    AIBuilderBudgetSettingsUpdate,
    FlowEvidencePolicyPublic,
    FlowEvidencePolicyUpdate,
    FlowInputLimitsPublic,
    FlowInputLimitsUpdate,
    FlowRetentionPolicyPublic,
    FlowRetentionPolicyUpdate,
    GetModelsResponse,
    SettingsPublic,
    ToggleSettingUpdate,
)

logger = get_logger(__name__)

router = APIRouter()
settings_admin_router = APIRouter()


class _FlowSettingsServiceProtocol(Protocol):
    async def get_flow_input_limits(self) -> FlowInputLimitsPublic: ...
    async def update_flow_input_limits(
        self, payload: FlowInputLimitsUpdate
    ) -> FlowInputLimitsPublic: ...
    async def get_flow_evidence_policy(self) -> FlowEvidencePolicyPublic: ...
    async def update_flow_evidence_policy(
        self, payload: FlowEvidencePolicyUpdate
    ) -> FlowEvidencePolicyPublic: ...
    async def get_flow_retention_policy(self) -> FlowRetentionPolicyPublic: ...
    async def update_flow_retention_policy(
        self, payload: FlowRetentionPolicyUpdate
    ) -> FlowRetentionPolicyPublic: ...
    async def get_ai_builder_budget_settings(self) -> AIBuilderBudgetSettingsPublic: ...
    async def update_ai_builder_budget_settings(
        self, payload: AIBuilderBudgetSettingsUpdate
    ) -> AIBuilderBudgetSettingsPublic: ...


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
    return to_paginated_response(supported_mimes())


@settings_admin_router.get(
    "/flow-input-limits",
    response_model=FlowInputLimitsPublic,
    summary="Get flow input limits",
    description="Return the tenant's effective upload limits for flow runtime inputs.",
)
async def get_flow_input_limits(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowInputLimitsPublic:
    validate_permission(container.user(), Permission.ADMIN)
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.get_flow_input_limits()


@settings_admin_router.patch(
    "/flow-input-limits",
    response_model=FlowInputLimitsPublic,
    summary="Update flow input limits",
    description=(
        "Update tenant-level upload limits used by flow runtime input endpoints. "
        "Omit a field to leave it unchanged. Send null to remove that tenant "
        "override and fall back to the default policy. Send a positive integer "
        "to set a tenant override."
    ),
    responses={
        400: {"description": "Invalid flow input limit payload."},
        403: {"description": "Caller lacks permission to update tenant settings."},
    },
)
async def update_flow_input_limits(
    payload: FlowInputLimitsUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowInputLimitsPublic:
    validate_permission(container.user(), Permission.ADMIN)
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.update_flow_input_limits(payload)


@settings_admin_router.get(
    "/flow-evidence-policy",
    response_model=FlowEvidencePolicyPublic,
    summary="Get flow evidence policy",
    description="Return the tenant's effective flow evidence export policy, including classification-3 raw export defaults.",
)
async def get_flow_evidence_policy(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowEvidencePolicyPublic:
    validate_permission(container.user(), Permission.ADMIN)
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.get_flow_evidence_policy()


@settings_admin_router.patch(
    "/flow-evidence-policy",
    response_model=FlowEvidencePolicyPublic,
    summary="Update flow evidence policy",
    description="Update tenant-level policy flags that control raw evidence export behavior for classification-3 spaces.",
)
async def update_flow_evidence_policy(
    payload: FlowEvidencePolicyUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowEvidencePolicyPublic:
    validate_permission(container.user(), Permission.ADMIN)
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.update_flow_evidence_policy(payload)


@settings_admin_router.get(
    "/flow-retention-policy",
    response_model=FlowRetentionPolicyPublic,
    summary="Get flow retention policy",
    description="Return the tenant's effective layered flow retention policy defaults and class-specific overrides.",
)
async def get_flow_retention_policy(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowRetentionPolicyPublic:
    validate_permission(container.user(), Permission.ADMIN)
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.get_flow_retention_policy()


@settings_admin_router.patch(
    "/flow-retention-policy",
    response_model=FlowRetentionPolicyPublic,
    summary="Update flow retention policy",
    description="Update tenant-level layered flow retention defaults and class-specific overrides used by Flow runtime data classes.",
)
async def update_flow_retention_policy(
    payload: FlowRetentionPolicyUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowRetentionPolicyPublic:
    validate_permission(container.user(), Permission.ADMIN)
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.update_flow_retention_policy(payload)


@settings_admin_router.get(
    "/ai-builder-budget",
    response_model=AIBuilderBudgetSettingsPublic,
    summary="Get AI Builder budget settings",
    description="Return token budget settings used by the Flow AI Builder planner.",
)
async def get_ai_builder_budget_settings(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> AIBuilderBudgetSettingsPublic:
    validate_permission(container.user(), Permission.ADMIN)
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.get_ai_builder_budget_settings()


@settings_admin_router.patch(
    "/ai-builder-budget",
    response_model=AIBuilderBudgetSettingsPublic,
    summary="Update AI Builder budget settings",
    description="Update token budget settings used by the Flow AI Builder planner.",
)
async def update_ai_builder_budget_settings(
    payload: AIBuilderBudgetSettingsUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> AIBuilderBudgetSettingsPublic:
    validate_permission(container.user(), Permission.ADMIN)
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.update_ai_builder_budget_settings(payload)


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
