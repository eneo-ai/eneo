from typing import Annotated, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response, status

from eneo.authentication import auth_dependencies
from eneo.data_retention.infrastructure.data_retention_service import (
    FLOW_RETENTION_PREVIEW_STALE_CODE,
    FlowRetentionChangeConfirmation,
)
from eneo.files.mime_support import supported_mimes
from eneo.flows.domain.flow_classification_retention_policy import (
    FlowClassificationRetentionPolicy,
)
from eneo.main.container.container import Container
from eneo.main.exceptions import ErrorCodes
from eneo.main.logging import get_logger
from eneo.main.models import GeneralError, PaginatedResponse
from eneo.roles.permissions import Permission, validate_permission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses, to_paginated_response
from eneo.settings import settings_factory
from eneo.settings.setting_service import (
    FLOW_SETTINGS_INVALID_PAYLOAD_CODE,
    SettingService,
)
from eneo.settings.settings import (
    AIBuilderBudgetSettingsPublic,
    AIBuilderBudgetSettingsUpdate,
    FlowClassificationRetentionPoliciesPublic,
    FlowClassificationRetentionPolicyPreviewRequest,
    FlowClassificationRetentionPolicyPublic,
    FlowClassificationRetentionPolicyUpdate,
    FlowDocumentRenderLimitsPublic,
    FlowDocumentRenderLimitsUpdate,
    FlowEvidencePolicyPublic,
    FlowEvidencePolicyUpdate,
    FlowInputLimitsPublic,
    FlowInputLimitsUpdate,
    FlowRetentionImpactPreviewPublic,
    FlowRetentionOrganizationPreviewRequest,
    FlowRetentionPolicyPublic,
    FlowRetentionPolicyUpdate,
    FlowRuntimePolicyPublic,
    FlowRuntimePolicyUpdate,
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
    async def get_flow_document_render_limits(
        self,
    ) -> FlowDocumentRenderLimitsPublic: ...
    async def update_flow_document_render_limits(
        self, payload: FlowDocumentRenderLimitsUpdate
    ) -> FlowDocumentRenderLimitsPublic: ...
    async def get_flow_runtime_policy(self) -> FlowRuntimePolicyPublic: ...
    async def update_flow_runtime_policy(
        self, payload: FlowRuntimePolicyUpdate
    ) -> FlowRuntimePolicyPublic: ...
    async def get_flow_evidence_policy(self) -> FlowEvidencePolicyPublic: ...
    async def update_flow_evidence_policy(
        self, payload: FlowEvidencePolicyUpdate
    ) -> FlowEvidencePolicyPublic: ...
    async def get_flow_retention_policy(self) -> FlowRetentionPolicyPublic: ...
    async def preview_flow_retention_policy(
        self, payload: FlowRetentionOrganizationPreviewRequest
    ) -> FlowRetentionImpactPreviewPublic: ...
    async def update_flow_retention_policy(
        self, payload: FlowRetentionPolicyUpdate
    ) -> FlowRetentionPolicyPublic: ...
    async def get_ai_builder_budget_settings(self) -> AIBuilderBudgetSettingsPublic: ...
    async def update_ai_builder_budget_settings(
        self, payload: AIBuilderBudgetSettingsUpdate
    ) -> AIBuilderBudgetSettingsPublic: ...


def _settings_error_response(
    *,
    description: str,
    message: str,
    eneo_error_code: ErrorCodes,
    code: str,
) -> dict[str, object]:
    return {
        "model": GeneralError,
        "description": description,
        "content": {
            "application/json": {
                "example": {
                    "message": message,
                    "eneo_error_code": int(eneo_error_code),
                    "code": code,
                }
            }
        },
    }


def _flow_settings_admin_forbidden_response() -> dict[str, object]:
    return _settings_error_response(
        description=(
            "Caller lacks tenant admin permission to read or update Flow tenant settings."
        ),
        message="Insufficient permissions.",
        eneo_error_code=ErrorCodes.UNAUTHORIZED,
        code="insufficient_tenant_permission",
    )


def _flow_settings_invalid_payload_response(
    description: str,
    message: str,
) -> dict[str, object]:
    return _settings_error_response(
        description=description,
        message=message,
        eneo_error_code=ErrorCodes.BAD_REQUEST,
        code=FLOW_SETTINGS_INVALID_PAYLOAD_CODE,
    )


def _flow_settings_not_found_response(description: str) -> dict[str, object]:
    return _settings_error_response(
        description=description,
        message="Not found.",
        eneo_error_code=ErrorCodes.NOT_FOUND,
        code="not_found",
    )


def _flow_retention_conflict_response() -> dict[str, object]:
    return _settings_error_response(
        description=(
            "The destructive change requires a fresh exact preview, or the "
            "control-plane/preview state changed before confirmation."
        ),
        message="Request a new Flow retention preview and confirm it.",
        eneo_error_code=ErrorCodes.CONFLICT,
        code=FLOW_RETENTION_PREVIEW_STALE_CODE,
    )


def _flow_retention_confirmation(
    payload: FlowRetentionPolicyUpdate | FlowClassificationRetentionPolicyUpdate,
) -> FlowRetentionChangeConfirmation | None:
    if payload.confirmation is None:
        return None
    return FlowRetentionChangeConfirmation(
        expected_control_plane_version=(
            payload.confirmation.expected_control_plane_version
        ),
        expected_preview_hash=payload.confirmation.expected_preview_hash,
        previewed_at=payload.confirmation.previewed_at,
    )


def _flow_classification_retention_policy_public(
    policy: FlowClassificationRetentionPolicy,
) -> FlowClassificationRetentionPolicyPublic:
    return FlowClassificationRetentionPolicyPublic(
        security_classification_id=policy.security_classification_id,
        data_retention_days=policy.data_retention_days,
    )


@router.get(
    "/",
    response_model=SettingsPublic,
    description="Get the current tenant settings.",
    responses=responses.get_responses([]),
)
async def get_settings(
    service: Annotated[
        SettingService,
        Depends(settings_factory.get_settings_service_allowing_read_only_key),
    ],
):
    return await service.get_settings()


@settings_admin_router.post(
    "/",
    response_model=SettingsPublic,
    description="Update tenant settings; omitted fields are not updated.",
    responses=responses.get_responses([403]),
)
async def upsert_settings(
    settings: SettingsPublic,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """Omitted fields are not updated."""
    validate_permission(container.user(), Permission.ADMIN)
    service = container.settings_service()
    return await service.update_settings(settings)


@router.get(
    "/models/",
    response_model=GetModelsResponse,
    description="List available completion and embedding models.",
    responses=responses.get_responses([]),
)
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
    description="List supported file format mime types.",
    responses=responses.get_responses([]),
    dependencies=[Depends(auth_dependencies.get_current_active_user)],
)
def get_formats():
    return to_paginated_response(supported_mimes())


@settings_admin_router.get(
    "/flow-input-limits",
    response_model=FlowInputLimitsPublic,
    operation_id="get_flow_input_limits",
    summary="Get flow input limits",
    description=(
        "Return the tenant's effective upload limits for Flow runtime inputs. "
        "Authoring and runtime clients use these values indirectly through the "
        "run-contract and upload endpoints; admin UIs use this endpoint to inspect "
        "the tenant-level policy that constrains audio, document, image, and generic "
        "file uploads before a run is created."
    ),
    responses={403: _flow_settings_admin_forbidden_response()},
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
    operation_id="update_flow_input_limits",
    summary="Update flow input limits",
    description=(
        "Update tenant-level upload limits used by flow runtime input endpoints. "
        "Omit a field to leave it unchanged. Send null to remove that tenant "
        "override and fall back to the default policy. Send a positive integer to set "
        "a tenant override. The returned payload is the resolved effective policy after "
        "the update, so API consumers can immediately refresh upload forms and progress "
        "timeout calculations."
    ),
    responses={
        400: _flow_settings_invalid_payload_response(
            "Invalid flow input limit payload.",
            "At least one flow input limit field must be provided.",
        ),
        403: _flow_settings_admin_forbidden_response(),
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
    "/flow-document-render-limits",
    response_model=FlowDocumentRenderLimitsPublic,
    operation_id="get_flow_document_render_limits",
    summary="Get flow document render limits",
    description=(
        "Return tenant-level guardrails for generated Flow PDF/DOCX outputs. These "
        "limits protect document-rendering workers from oversized text, tables, lists, "
        "and deeply nested structured output. Admin UIs should show these values as "
        "runtime safety ceilings, not as prompt or upload limits."
    ),
    responses={403: _flow_settings_admin_forbidden_response()},
)
async def get_flow_document_render_limits(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowDocumentRenderLimitsPublic:
    validate_permission(container.user(), Permission.ADMIN)
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.get_flow_document_render_limits()


@settings_admin_router.patch(
    "/flow-document-render-limits",
    response_model=FlowDocumentRenderLimitsPublic,
    operation_id="update_flow_document_render_limits",
    summary="Update flow document render limits",
    description=(
        "Update tenant-level guardrails for generated flow PDF/DOCX outputs. "
        "Omit a field to leave it unchanged. Send null to remove the tenant "
        "override and fall back to the product default. The response returns the "
        "resolved effective limits that document-generation steps will enforce for "
        "future runs."
    ),
    responses={
        400: _flow_settings_invalid_payload_response(
            "Invalid flow document render limit payload.",
            "At least one flow document render limit field must be provided.",
        ),
        403: _flow_settings_admin_forbidden_response(),
    },
)
async def update_flow_document_render_limits(
    payload: FlowDocumentRenderLimitsUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowDocumentRenderLimitsPublic:
    validate_permission(container.user(), Permission.ADMIN)
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.update_flow_document_render_limits(payload)


@settings_admin_router.get(
    "/flow-runtime-policy",
    response_model=FlowRuntimePolicyPublic,
    operation_id="get_flow_runtime_policy",
    summary="Get flow runtime policy",
    description=(
        "Return tenant-level per-step LLM runtime timeout policy for Flow executions. "
        "This controls backend worker timeouts for individual steps; it is separate "
        "from browser upload timeouts, document-rendering limits, and human-review "
        "expiry windows."
    ),
    responses={403: _flow_settings_admin_forbidden_response()},
)
async def get_flow_runtime_policy(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowRuntimePolicyPublic:
    validate_permission(container.user(), Permission.ADMIN)
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.get_flow_runtime_policy()


@settings_admin_router.patch(
    "/flow-runtime-policy",
    response_model=FlowRuntimePolicyPublic,
    operation_id="update_flow_runtime_policy",
    summary="Update flow runtime policy",
    description=(
        "Update tenant-level per-step LLM timeout policy for flow executions. "
        "Omit a field to leave it unchanged. Send null to remove the tenant "
        "override and fall back to the deployment default. The returned policy is the "
        "resolved effective timeout policy used by future Flow step executions."
    ),
    responses={
        400: _flow_settings_invalid_payload_response(
            "Invalid flow runtime policy payload.",
            "At least one flow runtime policy field must be provided.",
        ),
        403: _flow_settings_admin_forbidden_response(),
    },
)
async def update_flow_runtime_policy(
    payload: FlowRuntimePolicyUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowRuntimePolicyPublic:
    validate_permission(container.user(), Permission.ADMIN)
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.update_flow_runtime_policy(payload)


@settings_admin_router.get(
    "/flow-evidence-policy",
    response_model=FlowEvidencePolicyPublic,
    operation_id="get_flow_evidence_policy",
    summary="Get flow evidence policy",
    description=(
        "Return the tenant's effective Flow evidence export policy, including "
        "classification-3 raw-export defaults. This endpoint is for tenant admin UIs "
        "that need to explain whether raw evidence exports are allowed for space "
        "admins, run owners, or service-key principals."
    ),
    responses={403: _flow_settings_admin_forbidden_response()},
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
    operation_id="update_flow_evidence_policy",
    summary="Update flow evidence policy",
    description=(
        "Update tenant-level policy flags that control raw Flow evidence export "
        "behavior for classification-3 spaces. Omitted fields are left unchanged; "
        "boolean values explicitly enable or disable the corresponding raw-export "
        "capability for future evidence export requests."
    ),
    responses={
        400: _flow_settings_invalid_payload_response(
            "Invalid flow evidence policy payload.",
            "At least one flow evidence policy field must be provided.",
        ),
        403: _flow_settings_admin_forbidden_response(),
    },
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
    operation_id="get_flow_retention_policy",
    summary="Get flow retention policy",
    description=(
        "Return the tenant-admin Flow deletion envelope and the independent "
        "debug-evidence cleanup value. Null organization run-history and runtime-upload "
        "values mean Off. Classification policies can also activate the run-history "
        "envelope. This control plane must not be deployed without the canonical "
        "WI-19B selector adoption; this endpoint does not itself delete data."
    ),
    responses={403: _flow_settings_admin_forbidden_response()},
)
async def get_flow_retention_policy(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowRetentionPolicyPublic:
    validate_permission(container.user(), Permission.ADMIN)
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.get_flow_retention_policy()


@settings_admin_router.post(
    "/flow-retention-policy/preview",
    response_model=FlowRetentionImpactPreviewPublic,
    operation_id="preview_flow_retention_policy",
    summary="Preview a flow retention policy change",
    description=(
        "Read a bounded, set-based impact preview for exact proposed organization "
        "run-history and never-attached runtime-upload values. The preview includes "
        "counts, distinct file bytes, fixed clock anchors, latent Flow/Space values, "
        "and lifecycle blockers. It changes no policy and deletes no data."
    ),
    responses={403: _flow_settings_admin_forbidden_response()},
)
async def preview_flow_retention_policy(
    payload: FlowRetentionOrganizationPreviewRequest,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowRetentionImpactPreviewPublic:
    validate_permission(container.user(), Permission.ADMIN)
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.preview_flow_retention_policy(payload)


@settings_admin_router.patch(
    "/flow-retention-policy",
    response_model=FlowRetentionPolicyPublic,
    operation_id="update_flow_retention_policy",
    summary="Update flow retention policy",
    description=(
        "Update tenant Flow retention inputs. Omitted fields are unchanged and null "
        "means Off. Enabling or shortening organization run-history or never-attached "
        "upload retention requires the exact fresh preview confirmation returned by "
        "/flow-retention-policy/preview. Disabling or lengthening does not require "
        "confirmation. run_debug_evidence_days remains independent JSONB cleanup."
    ),
    responses={
        400: _flow_settings_invalid_payload_response(
            "Invalid flow retention policy payload.",
            "At least one flow retention policy field must be provided.",
        ),
        403: _flow_settings_admin_forbidden_response(),
        409: _flow_retention_conflict_response(),
    },
)
async def update_flow_retention_policy(
    payload: FlowRetentionPolicyUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowRetentionPolicyPublic:
    validate_permission(container.user(), Permission.ADMIN)
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.update_flow_retention_policy(payload)


@settings_admin_router.get(
    "/flow-classification-retention-policies",
    response_model=FlowClassificationRetentionPoliciesPublic,
    operation_id="list_flow_classification_retention_policies",
    summary="List flow classification retention policies",
    description=(
        "List tenant Flow classification retention control-plane inputs. A row can "
        "activate the full run history and step history envelope for spaces carrying "
        "its classification id, including while security_enabled is false. "
        "Debug-evidence cleanup is independent. These inputs must not be deployed "
        "without WI-19B selector adoption; listing policies does not delete data."
    ),
    responses={403: _flow_settings_admin_forbidden_response()},
)
async def list_flow_classification_retention_policies(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowClassificationRetentionPoliciesPublic:
    validate_permission(container.user(), Permission.ADMIN)
    service = container.flow_classification_retention_policy_service()
    policies = await service.list_policies()
    return FlowClassificationRetentionPoliciesPublic(
        policies=[
            _flow_classification_retention_policy_public(policy) for policy in policies
        ]
    )


@settings_admin_router.put(
    "/flow-classification-retention-policies/{security_classification_id}",
    response_model=FlowClassificationRetentionPolicyPublic,
    operation_id="put_flow_classification_retention_policy",
    summary="Set flow classification retention policy",
    description=(
        "Create or replace the run-history envelope input for one tenant security "
        "classification. Enabling or shortening requires the exact fresh evidence "
        "from the classification preview endpoint; lengthening does not. Once the "
        "WI-19B selector gate is integrated, the shortest active organization, "
        "classification, Space, and Flow value wins. This endpoint itself deletes "
        "no data and does not configure debug-evidence redaction."
    ),
    responses={
        403: _flow_settings_admin_forbidden_response(),
        404: _flow_settings_not_found_response(
            "Security classification does not exist for this tenant."
        ),
        409: _flow_retention_conflict_response(),
    },
)
async def put_flow_classification_retention_policy(
    security_classification_id: Annotated[
        UUID,
        Path(description="Tenant security classification id to bind the policy to."),
    ],
    payload: FlowClassificationRetentionPolicyUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowClassificationRetentionPolicyPublic:
    validate_permission(container.user(), Permission.ADMIN)
    service = container.flow_classification_retention_policy_service()
    policy = await service.set_policy(
        security_classification_id=security_classification_id,
        data_retention_days=payload.data_retention_days,
        confirmation=_flow_retention_confirmation(payload),
    )
    return _flow_classification_retention_policy_public(policy)


@settings_admin_router.post(
    "/flow-classification-retention-policies/{security_classification_id}/preview",
    response_model=FlowRetentionImpactPreviewPublic,
    operation_id="preview_flow_classification_retention_policy",
    summary="Preview a flow classification retention policy change",
    description=(
        "Use the same exact-state, set-based Flow retention gate as organization "
        "policy changes before enabling or shortening a classification policy. "
        "This bounded read returns the control-plane version, preview hash, fixed "
        "clock anchor, counts, distinct file bytes, latent Flow/Space values, and "
        "lifecycle blockers needed to confirm the proposal without deleting data."
    ),
    responses={
        403: _flow_settings_admin_forbidden_response(),
        404: _flow_settings_not_found_response(
            "Security classification does not exist for this tenant."
        ),
    },
)
async def preview_flow_classification_retention_policy(
    security_classification_id: Annotated[
        UUID,
        Path(description="Tenant security classification id to preview."),
    ],
    payload: FlowClassificationRetentionPolicyPreviewRequest,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowRetentionImpactPreviewPublic:
    validate_permission(container.user(), Permission.ADMIN)
    service = container.flow_classification_retention_policy_service()
    preview = await service.preview_policy(
        security_classification_id=security_classification_id,
        data_retention_days=payload.data_retention_days,
    )
    return FlowRetentionImpactPreviewPublic.from_domain(preview)


@settings_admin_router.delete(
    "/flow-classification-retention-policies/{security_classification_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="delete_flow_classification_retention_policy",
    summary="Delete flow classification retention policy",
    description=(
        "Delete the Flow classification retention policy for one tenant security "
        "classification. The delete is idempotent when the classification exists "
        "but has no policy row. If the classification itself is missing or belongs "
        "to another tenant, the endpoint returns 404. Removing an activation input "
        "can only disable or lengthen future eligibility, so destructive preview "
        "confirmation is not required."
    ),
    responses={
        403: _flow_settings_admin_forbidden_response(),
        404: _flow_settings_not_found_response(
            "Security classification does not exist for this tenant."
        ),
    },
)
async def delete_flow_classification_retention_policy(
    security_classification_id: Annotated[
        UUID,
        Path(description="Tenant security classification id whose policy is removed."),
    ],
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> Response:
    validate_permission(container.user(), Permission.ADMIN)
    service = container.flow_classification_retention_policy_service()
    await service.delete_policy(
        security_classification_id=security_classification_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@settings_admin_router.get(
    "/ai-builder-budget",
    response_model=AIBuilderBudgetSettingsPublic,
    summary="Get AI Builder budget settings",
    description="Return token budget settings used by the Flow AI Builder planner.",
    responses={403: _flow_settings_admin_forbidden_response()},
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
    responses={
        400: _flow_settings_invalid_payload_response(
            "Invalid AI Builder budget settings payload.",
            "At least one AI Builder budget field must be provided.",
        ),
        403: _flow_settings_admin_forbidden_response(),
    },
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
    responses=responses.get_responses([403]),
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
    responses=responses.get_responses([403]),
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
    responses=responses.get_responses([403]),
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
    responses=responses.get_responses([403]),
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
