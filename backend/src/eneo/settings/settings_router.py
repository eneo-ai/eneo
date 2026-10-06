from typing import Annotated, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eneo.authentication import auth_dependencies
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.data_retention.infrastructure.retention_lock import RetentionSubject
from eneo.files.mime_support import supported_mimes
from eneo.flows.application.flow_retention_authz import (
    RETENTION_PERMISSION_REQUIRED_CODE,
    RETENTION_PERSON_REQUIRED_CODE,
)
from eneo.flows.domain.flow_retention_hold import (
    FLOW_RETENTION_HOLD_ALREADY_RELEASED_CODE,
    FLOW_RETENTION_HOLD_END_NOT_IN_FUTURE_CODE,
    FLOW_RETENTION_HOLD_NOT_ACTIVE_CODE,
    FLOW_RETENTION_HOLD_REVIEW_NOT_LATER_CODE,
    FLOW_RETENTION_HOLD_REVIEW_OUT_OF_RANGE_CODE,
    FLOW_RETENTION_HOLD_RUN_NOT_IN_FLOW_CODE,
    MAX_FLOW_RETENTION_HOLD_PAGE_SIZE,
    FlowRetentionHold,
    FlowRetentionHoldCreateRequest,
    FlowRetentionHoldExtendReviewRequest,
    FlowRetentionHoldPage,
    FlowRetentionHoldPlacement,
    FlowRetentionHoldReleaseRequest,
    FlowRetentionHoldReviewLimit,
    FlowRetentionHoldReviewLimitUpdate,
    FlowRetentionHoldStatusFilter,
)
from eneo.flows.domain.flow_run_history_deletion_status import (
    FlowRunHistoryDeletionStatus,
)
from eneo.flows.domain.flow_run_retention_policy import (
    FLOW_RETENTION_AUTO_DELETE_UNAVAILABLE_CODE,
    FLOW_RETENTION_DAYS_ABOVE_MAXIMUM_CODE,
    FLOW_RETENTION_REASON_REQUIRED_CODE,
    FlowRunRetentionFlowTargetPage,
    FlowRunRetentionPolicySettings,
    FlowRunRetentionReviewCursor,
    FlowRunRetentionReviewPage,
    FlowRunRetentionSpaceTargetPage,
)
from eneo.main.container.container import Container
from eneo.main.exceptions import BadRequestException, ErrorCodes
from eneo.main.logging import get_logger
from eneo.main.models import GeneralError, PaginatedResponse
from eneo.roles.permissions import Permission
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
    FlowDocumentRenderLimitsPublic,
    FlowDocumentRenderLimitsUpdate,
    FlowEvidencePolicyPublic,
    FlowEvidencePolicyUpdate,
    FlowInputLimitsPublic,
    FlowInputLimitsUpdate,
    FlowMappedExecutionPolicyPublic,
    FlowMappedExecutionPolicyUpdate,
    FlowRagEvidencePolicyPublic,
    FlowRagEvidencePolicyUpdate,
    FlowRetentionPolicyPublic,
    FlowRetentionPolicyUpdate,
    FlowRunHistoryPurgePublic,
    FlowRunHistoryPurgeRequest,
    FlowRunRetentionPolicyReplaceRequest,
    FlowRuntimePolicyPublic,
    FlowRuntimePolicyUpdate,
    GetModelsResponse,
    SettingsBase,
    SettingsPublic,
    SkillExecutionBlockState,
    SkillExecutionBlockUpdate,
    SkillExecutionUnblockUpdate,
    SkillRuntimeModelProjections,
    SkillRuntimePolicyPublic,
    SkillRuntimePolicyUpdate,
    ToggleSettingUpdate,
)

logger = get_logger(__name__)

router = APIRouter()
settings_admin_router = APIRouter()
_TENANT_SETTINGS_ADMIN_ACCESS_REASON = (
    "Administering tenant settings requires the admin permission."
)

FlowRetentionMutationContainer = Annotated[
    Container,
    Depends(get_container(with_user=True, transaction_scope="function")),
]


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
    async def get_mapped_execution_policy(self) -> FlowMappedExecutionPolicyPublic: ...
    async def update_mapped_execution_policy(
        self, payload: FlowMappedExecutionPolicyUpdate
    ) -> FlowMappedExecutionPolicyPublic: ...
    async def get_rag_evidence_policy(self) -> FlowRagEvidencePolicyPublic: ...
    async def update_rag_evidence_policy(
        self, payload: FlowRagEvidencePolicyUpdate
    ) -> FlowRagEvidencePolicyPublic: ...
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


_RETENTION_ACCESS_REASON = (
    "Any signed-in caller is admitted; the Flow retention authorization owner "
    "(flows retention authz) requires retention_manage or retention_holds and "
    "refuses API keys."
)
_RETENTION_PERMISSION_TEXT = {
    "manage": "retention_manage",
    "holds": "retention_holds",
    "view": "retention_manage or retention_holds",
}


def _retention_forbidden_response(kind: str) -> dict[str, object]:
    return _settings_error_response(
        description=(
            f"Caller lacks {_RETENTION_PERMISSION_TEXT[kind]} "
            f"(`{RETENTION_PERMISSION_REQUIRED_CODE}`), or used an API key: "
            f"retention is changed or stopped by signed-in people only "
            f"(`{RETENTION_PERSON_REQUIRED_CODE}`)."
        ),
        message=f"Need permission {_RETENTION_PERMISSION_TEXT[kind]}.",
        eneo_error_code=ErrorCodes.UNAUTHORIZED,
        code=RETENTION_PERMISSION_REQUIRED_CODE,
    )


def _flow_retention_review_cursor(
    value: str | None,
) -> FlowRunRetentionReviewCursor | None:
    if value is None:
        return None
    try:
        return FlowRunRetentionReviewCursor.deserialize(value)
    except ValueError as exc:
        raise BadRequestException(
            "Invalid Flow retention review cursor.",
            code="invalid_flow_retention_review_cursor",
        ) from exc


def _flow_retention_invalid_cursor_response() -> dict[str, object]:
    return _settings_error_response(
        description="The Flow retention review cursor is malformed or unsupported.",
        message="Invalid Flow retention review cursor.",
        eneo_error_code=ErrorCodes.BAD_REQUEST,
        code="invalid_flow_retention_review_cursor",
    )


def _flow_retention_not_found_response(entity: str) -> dict[str, object]:
    return _settings_error_response(
        description=f"{entity} not found in the administrator's Organization.",
        message=f"{entity} not found.",
        eneo_error_code=ErrorCodes.NOT_FOUND,
        code="not_found",
    )


_FLOW_RETENTION_LOCK_BUSY_CODE = RetentionSubject.FLOW_HISTORY.busy_code


def _flow_retention_lock_busy_response() -> dict[str, object]:
    return _settings_error_response(
        description=(
            "Another retention change or history deletion held the retention lock "
            f"too long (`{_FLOW_RETENTION_LOCK_BUSY_CODE}`). Nothing changed; retry."
        ),
        message="Flow history retention is busy with another change or deletion.",
        eneo_error_code=ErrorCodes.CONFLICT,
        code=_FLOW_RETENTION_LOCK_BUSY_CODE,
    )


def _flow_retention_policy_write_refused_response() -> dict[str, object]:
    return _settings_error_response(
        description=(
            "The policy cannot be written: auto_delete before this deployment "
            f"offers it (`{FLOW_RETENTION_AUTO_DELETE_UNAVAILABLE_CODE}`), more days "
            f"than the deployment's maximum (`{FLOW_RETENTION_DAYS_ABOVE_MAXIMUM_CODE}`"
            "; write_rules.max_days), or a change that stops or delays automatic "
            f"deletion without a reason (`{FLOW_RETENTION_REASON_REQUIRED_CODE}`). "
            "Nothing changed."
        ),
        message="Automatic deletion is not available in this deployment yet.",
        eneo_error_code=ErrorCodes.BAD_REQUEST,
        code=FLOW_RETENTION_AUTO_DELETE_UNAVAILABLE_CODE,
    )


_FLOW_RETENTION_WRITE_RULES_TEXT = (
    " Modes: preserve and review_required keep history until an explicit purge; "
    "auto_delete lets the nightly flows.history task delete terminal runs once "
    "they are older than the days, and is accepted only when write_rules."
    "auto_delete_available is true. Days may not exceed write_rules.max_days. A "
    "change that stops or delays automatic deletion at this level (auto_delete "
    "becomes another mode, is cleared, or gets more days) needs a reason, which "
    "the required audit event records with the previous and new policy."
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


@settings_admin_router.get(
    "/skills/{skill_id}/execution-block",
    response_model=SkillExecutionBlockState,
    responses=responses.get_responses([403, 404]),
    summary="Get an organisation Skill execution block",
    description="Return the active tenant-scoped execution block for one organisation Skill.",
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def get_skill_execution_block(
    skill_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _user_identity_guard: None = Depends(auth_dependencies.require_user_identity),
):
    return await container.settings_service().get_skill_execution_block(
        skill_id=skill_id
    )


@settings_admin_router.post(
    "/skills/{skill_id}/execution-block",
    response_model=SkillExecutionBlockState,
    responses=responses.get_responses([400, 403, 404]),
    summary="Block an organisation Skill from execution",
    description=(
        "Block every retained version of an organisation Skill from subsequent "
        "runtime composition without changing its bindings or history."
    ),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def block_skill_execution(
    skill_id: UUID,
    data: SkillExecutionBlockUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _user_identity_guard: None = Depends(auth_dependencies.require_user_identity),
):
    return await container.settings_service().block_skill_execution(
        skill_id=skill_id,
        reason=data.reason,
    )


@settings_admin_router.post(
    "/skills/{skill_id}/execution-block/unblock",
    response_model=SkillExecutionBlockState,
    responses=responses.get_responses([400, 403, 404, 409]),
    summary="Unblock an organisation Skill",
    description=(
        "Release the exact active execution block reviewed by the tenant administrator."
    ),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def unblock_skill_execution(
    skill_id: UUID,
    data: SkillExecutionUnblockUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _user_identity_guard: None = Depends(auth_dependencies.require_user_identity),
):
    return await container.settings_service().unblock_skill_execution(
        skill_id=skill_id,
        expected_block_id=data.expected_block_id,
        reason=data.reason,
    )


@settings_admin_router.get(
    "/skills/runtime-policy",
    response_model=SkillRuntimePolicyPublic,
    responses=responses.get_responses([403]),
    summary="Get the tenant Skill runtime policy",
    description=(
        "Return the stored organisation Skill runtime policy: selective-"
        "activation enablement, attachment limit, context share, and the "
        "per-turn activation ceiling."
    ),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def get_skill_runtime_policy(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _user_identity_guard: None = Depends(auth_dependencies.require_user_identity),
):
    return await container.settings_service().get_skill_runtime_policy()


@settings_admin_router.put(
    "/skills/runtime-policy",
    response_model=SkillRuntimePolicyPublic,
    responses=responses.get_responses([400, 403]),
    summary="Replace the tenant Skill runtime policy",
    description=(
        "Replace all stored Skill runtime policy values. The per-turn "
        "activation ceiling can be lowered but never raised past the "
        "platform bound."
    ),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def update_skill_runtime_policy(
    data: SkillRuntimePolicyUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _user_identity_guard: None = Depends(auth_dependencies.require_user_identity),
):
    return await container.settings_service().update_skill_runtime_policy(data)


@settings_admin_router.post(
    "/skills/runtime-policy/reset",
    response_model=SkillRuntimePolicyPublic,
    responses=responses.get_responses([403]),
    summary="Restore the seeded Skill runtime policy defaults",
    description=(
        "Restore the product-standard seeded values, which may differ from a "
        "deployment's migrated environment seed."
    ),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def reset_skill_runtime_policy(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _user_identity_guard: None = Depends(auth_dependencies.require_user_identity),
):
    return await container.settings_service().reset_skill_runtime_policy()


@settings_admin_router.get(
    "/skills/runtime-policy/model-projections",
    response_model=SkillRuntimeModelProjections,
    responses=responses.get_responses([403]),
    summary="Get per-model Skill context allowances",
    description=(
        "Return the read-only policy allowance for each accessible completion "
        "model: input window, native tool-calling support, and the token "
        "allowance produced by the configured context share."
    ),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def get_skill_runtime_model_projections(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _user_identity_guard: None = Depends(auth_dependencies.require_user_identity),
):
    return await container.settings_service().get_skill_runtime_model_projections()


@router.get(
    "/",
    response_model=SettingsPublic,
    description="Get the current tenant settings.",
    responses=responses.get_responses([]),
)
@endpoint_access(
    authentication=Authentication.ASSISTANT,
    authorization=Authorization.AUTHENTICATED,
    reason="Settings services return tenant-scoped configuration to authenticated callers.",
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
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def upsert_settings(
    settings: SettingsBase,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """Omitted fields are not updated."""
    service = container.settings_service()
    return await service.update_settings(settings)


@router.get(
    "/models/",
    response_model=GetModelsResponse,
    description="List available completion and embedding models.",
    responses=responses.get_responses([]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="Settings services return tenant-scoped configuration to authenticated callers.",
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
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="Settings services return tenant-scoped configuration to authenticated callers.",
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
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def get_flow_input_limits(
    container: Annotated[
        Container,
        Depends(get_container(with_user=True, with_upload_admission=True)),
    ],
) -> FlowInputLimitsPublic:
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
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def update_flow_input_limits(
    payload: FlowInputLimitsUpdate,
    container: Annotated[
        Container,
        Depends(get_container(with_user=True, with_upload_admission=True)),
    ],
) -> FlowInputLimitsPublic:
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
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def get_flow_document_render_limits(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowDocumentRenderLimitsPublic:
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
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def update_flow_document_render_limits(
    payload: FlowDocumentRenderLimitsUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowDocumentRenderLimitsPublic:
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.update_flow_document_render_limits(payload)


@settings_admin_router.get(
    "/flow-runtime-policy",
    response_model=FlowRuntimePolicyPublic,
    operation_id="get_flow_runtime_policy",
    summary="Get flow runtime policy",
    description=(
        "Return the runtime policy for Flow executions: per-step LLM "
        "timeouts and the limit on concurrent runs. The timeouts control backend "
        "worker timeouts for individual steps; they are separate from browser upload "
        "timeouts, document-rendering limits, and human-review expiry windows. "
        "`max_concurrent_runs` is the effective limit on queued and running runs "
        "and `max_concurrent_runs_capacity` the server capacity it cannot exceed."
    ),
    responses={403: _flow_settings_admin_forbidden_response()},
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def get_flow_runtime_policy(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowRuntimePolicyPublic:
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.get_flow_runtime_policy()


@settings_admin_router.patch(
    "/flow-runtime-policy",
    response_model=FlowRuntimePolicyPublic,
    operation_id="update_flow_runtime_policy",
    summary="Update flow runtime policy",
    description=(
        "Update the runtime policy for flow executions: per-step LLM "
        "timeouts and the limit on concurrent runs. "
        "Omit a field to leave it unchanged. Send null to remove the tenant "
        "override and fall back to the deployment default. A `max_concurrent_runs` "
        "above the server capacity is refused with "
        "`max_concurrent_runs_exceeds_server_capacity`, and a value equal to the "
        "capacity is stored as no override. The returned policy is the "
        "resolved effective policy used by future Flow runs and step executions."
    ),
    responses={
        400: _flow_settings_invalid_payload_response(
            "Invalid flow runtime policy payload.",
            "At least one flow runtime policy field must be provided.",
        ),
        403: _flow_settings_admin_forbidden_response(),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def update_flow_runtime_policy(
    payload: FlowRuntimePolicyUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowRuntimePolicyPublic:
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.update_flow_runtime_policy(payload)


@settings_admin_router.get(
    "/flow-mapped-execution-policy",
    response_model=FlowMappedExecutionPolicyPublic,
    operation_id="get_mapped_execution_policy",
    summary="Get mapped execution policy",
    description=(
        "Return the tenant ceilings for mapped provider-call fan-out and aggregate "
        "estimated input tokens. A null call ceiling blocks new mapped Builder "
        "authoring; a null token ceiling disables only that aggregate token check. "
        "Published definitions keep their explicit file or item bounds."
    ),
    responses={403: _flow_settings_admin_forbidden_response()},
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def get_mapped_execution_policy(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowMappedExecutionPolicyPublic:
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.get_mapped_execution_policy()


@settings_admin_router.patch(
    "/flow-mapped-execution-policy",
    response_model=FlowMappedExecutionPolicyPublic,
    operation_id="update_mapped_execution_policy",
    summary="Update mapped execution policy",
    description=(
        "Update the tenant ceilings for mapped provider calls and aggregate estimated "
        "input tokens. Omit a field to preserve it or send null to remove its tenant "
        "override. Lower call ceilings clamp future attempts without rewriting the "
        "explicit file or item bounds in published Flow definitions."
    ),
    responses={
        400: _flow_settings_invalid_payload_response(
            "Invalid mapped execution policy payload.",
            "At least one mapped execution policy field must be provided.",
        ),
        403: _flow_settings_admin_forbidden_response(),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def update_mapped_execution_policy(
    payload: FlowMappedExecutionPolicyUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowMappedExecutionPolicyPublic:
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.update_mapped_execution_policy(payload)


@settings_admin_router.get(
    "/flow-rag-evidence-policy",
    response_model=FlowRagEvidencePolicyPublic,
    operation_id="get_rag_evidence_policy",
    summary="Get knowledge evidence policy",
    description=(
        "Return how much retrieved passage text a Flow step records. Every source "
        "a step retrieved is always listed with its identity and match counts; "
        "these ceilings bound only the verbatim passage text kept alongside it."
    ),
    responses={403: _flow_settings_admin_forbidden_response()},
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def get_rag_evidence_policy(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowRagEvidencePolicyPublic:
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.get_rag_evidence_policy()


@settings_admin_router.patch(
    "/flow-rag-evidence-policy",
    response_model=FlowRagEvidencePolicyPublic,
    operation_id="update_rag_evidence_policy",
    summary="Update knowledge evidence policy",
    description=(
        "Change how much retrieved passage text new step attempts record. Omit a "
        "field to preserve it or send null to restore its default. Recorded "
        "passages hold verbatim source text, so each ceiling has a fixed maximum."
    ),
    responses={
        400: _flow_settings_invalid_payload_response(
            "Invalid knowledge evidence policy payload.",
            "At least one knowledge evidence policy field must be provided.",
        ),
        403: _flow_settings_admin_forbidden_response(),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def update_rag_evidence_policy(
    payload: FlowRagEvidencePolicyUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowRagEvidencePolicyPublic:
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.update_rag_evidence_policy(payload)


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
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def get_flow_evidence_policy(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowEvidencePolicyPublic:
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
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def update_flow_evidence_policy(
    payload: FlowEvidencePolicyUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowEvidencePolicyPublic:
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.update_flow_evidence_policy(payload)


@settings_admin_router.get(
    "/flow-retention-policy",
    response_model=FlowRetentionPolicyPublic,
    operation_id="get_flow_retention_policy",
    summary="Get flow retention policy",
    description=(
        "Return the eligibility window for stored Flow debug evidence and the keep "
        "window for runtime uploads never attached to a run (and unbound live "
        "transcripts), which the nightly gallring job deletes after it; null means "
        "the 30-day default. Flow run-history retention is configured "
        "through the dedicated hierarchical policy endpoints. Reading this endpoint "
        "never previews, deletes, or redacts Flow data."
    ),
    responses={403: _flow_settings_admin_forbidden_response()},
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def get_flow_retention_policy(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowRetentionPolicyPublic:
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.get_flow_retention_policy()


@settings_admin_router.patch(
    "/flow-retention-policy",
    response_model=FlowRetentionPolicyPublic,
    operation_id="update_flow_retention_policy",
    summary="Update flow retention policy",
    description=(
        "Update the eligibility window for stored Flow debug evidence and the keep "
        "window for runtime uploads never attached to a run. Omitted fields are "
        "unchanged and null removes the tenant input (uploads then use the 30-day "
        "default). Saving these values never deletes or redacts Flow data; the "
        "nightly gallring job applies the upload window. The upload window is a "
        "retention decision: changing it also needs retention_manage in a "
        f"signed-in session (`{RETENTION_PERMISSION_REQUIRED_CODE}`, "
        f"`{RETENTION_PERSON_REQUIRED_CODE}`), a longer window needs a reason "
        f"(`{FLOW_RETENTION_REASON_REQUIRED_CODE}`), and a change writes the required "
        "audit action flow_run_retention_policy_changed with the previous and new "
        "value and the reason in the same transaction. It waits for an open "
        "history deletion to finish."
    ),
    responses={
        400: _flow_settings_invalid_payload_response(
            "Invalid flow retention policy payload.",
            "At least one flow retention policy field must be provided.",
        ),
        403: _flow_settings_admin_forbidden_response(),
        409: _flow_retention_lock_busy_response(),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def update_flow_retention_policy(
    payload: FlowRetentionPolicyUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowRetentionPolicyPublic:
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.update_flow_retention_policy(payload)


@settings_admin_router.get(
    "/flow-run-retention-policy",
    response_model=FlowRunRetentionPolicySettings,
    operation_id="get_organization_flow_run_retention_policy",
    summary="Get the Organization Flow run-history retention policy",
    description=(
        "Return the Organization default and its effective Flow run-history policy. "
        "No configured policy means run history has no age threshold and remains stored."
    ),
    responses={403: _retention_forbidden_response("view")},
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RETENTION_ACCESS_REASON,
)
async def get_organization_flow_run_retention_policy(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowRunRetentionPolicySettings:
    return await container.flow_run_retention_policy_service().get_organization()


@settings_admin_router.put(
    "/flow-run-retention-policy",
    response_model=FlowRunRetentionPolicySettings,
    operation_id="replace_organization_flow_run_retention_policy",
    summary="Replace the Organization Flow run-history retention policy",
    description=(
        "Replace the complete Organization policy or clear it. The change waits "
        "for an open history deletion to finish." + _FLOW_RETENTION_WRITE_RULES_TEXT
    ),
    responses={
        400: _flow_retention_policy_write_refused_response(),
        403: _retention_forbidden_response("manage"),
        409: _flow_retention_lock_busy_response(),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RETENTION_ACCESS_REASON,
)
async def replace_organization_flow_run_retention_policy(
    payload: FlowRunRetentionPolicyReplaceRequest,
    container: FlowRetentionMutationContainer,
) -> FlowRunRetentionPolicySettings:
    return await container.flow_run_retention_policy_service().replace_organization(
        policy=payload.policy, reason=payload.reason
    )


@settings_admin_router.get(
    "/flow-run-retention-policy/status",
    response_model=FlowRunHistoryDeletionStatus,
    operation_id="get_flow_run_history_deletion_status",
    summary="Get the status of scheduled Flow run-history deletion",
    description=(
        "Every registered nightly gallring task with its switch, staleness and "
        "newest execution (outcome, counts, blocked counts, error code); Flow runs "
        "under auto_delete still stored past the overdue window after their "
        "deadline (a live count capped at 1000, by blocker, legal holds counted "
        "apart); and unfinished run deletions. The cap bounds returned results, "
        "not examined rows. Each statement uses "
        "GALLRING_CHUNK_STATEMENT_TIMEOUT_MS; statement or lock timeouts return 503 with "
        "code retention_status_unavailable. Ids, "
        "counts, timestamps and codes only. Readable with retention_manage or "
        "retention_holds."
    ),
    responses={
        403: _retention_forbidden_response("view"),
        503: {"description": "Retention status timed out; retry shortly."},
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RETENTION_ACCESS_REASON,
)
async def get_flow_run_history_deletion_status(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowRunHistoryDeletionStatus:
    return await container.flow_run_retention_policy_service().get_deletion_status()


@settings_admin_router.get(
    "/flow-run-retention-policy/hold-review-limit",
    response_model=FlowRetentionHoldReviewLimit,
    operation_id="get_flow_retention_hold_review_limit",
    summary="Get the review limit for legal holds",
    description=(
        "How far ahead, in days, a legal hold's review date may be set when it is "
        "placed or its review is moved, and whether the default of 365 days "
        "applies. Readable with retention_manage or retention_holds; changed with "
        "retention_manage."
    ),
    responses={403: _retention_forbidden_response("view")},
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RETENTION_ACCESS_REASON,
)
async def get_flow_retention_hold_review_limit(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowRetentionHoldReviewLimit:
    return await container.flow_run_retention_policy_service().get_hold_review_limit()


@settings_admin_router.put(
    "/flow-run-retention-policy/hold-review-limit",
    response_model=FlowRetentionHoldReviewLimit,
    operation_id="replace_flow_retention_hold_review_limit",
    summary="Replace the review limit for legal holds",
    description=(
        "Set how far ahead, in days, a legal hold's review date may be set, or null "
        "for the default of 365 days. Applies to holds placed or reviewed after the "
        "change. A change writes the required audit action "
        "flow_run_retention_policy_changed in the same transaction."
    ),
    responses={
        403: _retention_forbidden_response("manage"),
        409: _flow_retention_lock_busy_response(),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RETENTION_ACCESS_REASON,
)
async def replace_flow_retention_hold_review_limit(
    payload: FlowRetentionHoldReviewLimitUpdate,
    container: FlowRetentionMutationContainer,
) -> FlowRetentionHoldReviewLimit:
    return (
        await container.flow_run_retention_policy_service().replace_hold_review_limit(
            days=payload.days
        )
    )


@settings_admin_router.get(
    "/flow-run-retention-policy/targets/spaces",
    response_model=FlowRunRetentionSpaceTargetPage,
    operation_id="list_flow_run_retention_space_targets",
    summary="List Spaces available for Flow retention administration",
    description=(
        "List non-personal Spaces across the caller's Organization, including "
        "Spaces where the Organization administrator is not a member. The bounded "
        "response contains identifiers and names only."
    ),
    responses={403: _retention_forbidden_response("view")},
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RETENTION_ACCESS_REASON,
)
async def list_flow_run_retention_space_targets(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    limit: int = Query(default=200, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> FlowRunRetentionSpaceTargetPage:
    return await container.flow_run_retention_policy_service().list_space_targets(
        limit=limit,
        offset=offset,
    )


@settings_admin_router.get(
    "/flow-run-retention-policy/targets/spaces/{space_id}/flows",
    response_model=FlowRunRetentionFlowTargetPage,
    operation_id="list_flow_run_retention_flow_targets",
    summary="List Flows available for retention administration in a Space",
    description=(
        "List the Flows in one Organization-scoped Space, including Flows the "
        "Organization administrator cannot discover through membership-scoped Flow "
        "authoring APIs, and deleted Flows that still have run history (marked "
        "retired). The bounded response contains identifiers, names and the retired "
        "flag only."
    ),
    responses={
        403: _retention_forbidden_response("view"),
        404: _flow_retention_not_found_response("Space"),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RETENTION_ACCESS_REASON,
)
async def list_flow_run_retention_flow_targets(
    space_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    limit: int = Query(default=200, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> FlowRunRetentionFlowTargetPage:
    return await container.flow_run_retention_policy_service().list_flow_targets(
        space_id=space_id,
        limit=limit,
        offset=offset,
    )


@settings_admin_router.get(
    "/flow-run-retention-policy/spaces/{space_id}",
    response_model=FlowRunRetentionPolicySettings,
    operation_id="get_space_flow_run_retention_policy",
    summary="Get a Space Flow run-history retention policy",
    description=(
        "Return the Space override, the inherited Organization policy, and the "
        "effective policy. A complete Space policy replaces the Organization default "
        "for every Flow in that Space unless a Flow has its own complete override. "
        "The response names the winning source so an administrator can verify the "
        "result before any separate purge action. Reading it never deletes data."
    ),
    responses={
        403: _retention_forbidden_response("view"),
        404: _flow_retention_not_found_response("Space"),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RETENTION_ACCESS_REASON,
)
async def get_space_flow_run_retention_policy(
    space_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowRunRetentionPolicySettings:
    return await container.flow_run_retention_policy_service().get_space(
        space_id=space_id
    )


@settings_admin_router.put(
    "/flow-run-retention-policy/spaces/{space_id}",
    response_model=FlowRunRetentionPolicySettings,
    operation_id="replace_space_flow_run_retention_policy",
    summary="Replace a Space Flow run-history retention policy",
    description=(
        "Replace the complete Space override or clear it to inherit the Organization "
        "policy. The mode and day count move together, preventing ambiguous mixed "
        "inheritance. This setting controls Flow run history only: it does not change "
        "conversation or AI Builder retention. The change waits for an open history "
        "deletion to finish." + _FLOW_RETENTION_WRITE_RULES_TEXT
    ),
    responses={
        400: _flow_retention_policy_write_refused_response(),
        403: _retention_forbidden_response("manage"),
        404: _flow_retention_not_found_response("Space"),
        409: _flow_retention_lock_busy_response(),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RETENTION_ACCESS_REASON,
)
async def replace_space_flow_run_retention_policy(
    space_id: UUID,
    payload: FlowRunRetentionPolicyReplaceRequest,
    container: FlowRetentionMutationContainer,
) -> FlowRunRetentionPolicySettings:
    return await container.flow_run_retention_policy_service().replace_space(
        space_id=space_id,
        policy=payload.policy,
        reason=payload.reason,
    )


@settings_admin_router.get(
    "/flow-run-retention-policy/flows/{flow_id}",
    response_model=FlowRunRetentionPolicySettings,
    operation_id="get_flow_run_retention_policy",
    summary="Get a Flow run-history retention policy",
    description=(
        "Return the Flow override, the inherited Space or Organization policy, and "
        "the effective policy. A complete Flow policy replaces its inherited policy, "
        "which allows one Flow to keep 90 days while its Space keeps 60 and the "
        "Organization default remains 30. Reading the policy never deletes run data."
        " A deleted Flow is accepted."
    ),
    responses={
        403: _retention_forbidden_response("view"),
        404: _flow_retention_not_found_response("Flow"),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RETENTION_ACCESS_REASON,
)
async def get_flow_run_retention_policy(
    flow_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowRunRetentionPolicySettings:
    return await container.flow_run_retention_policy_service().get_flow(flow_id=flow_id)


@settings_admin_router.put(
    "/flow-run-retention-policy/flows/{flow_id}",
    response_model=FlowRunRetentionPolicySettings,
    operation_id="replace_flow_run_retention_policy",
    summary="Replace a Flow run-history retention policy",
    description=(
        "Replace the complete Flow override or clear it to inherit. Operational "
        "retention remains editable after a Flow definition is published because it "
        "does not mutate the published definition. A deleted Flow is accepted. The "
        "change waits for an open history deletion to finish."
        + _FLOW_RETENTION_WRITE_RULES_TEXT
    ),
    responses={
        400: _flow_retention_policy_write_refused_response(),
        403: _retention_forbidden_response("manage"),
        404: _flow_retention_not_found_response("Flow"),
        409: _flow_retention_lock_busy_response(),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RETENTION_ACCESS_REASON,
)
async def replace_flow_run_retention_policy(
    flow_id: UUID,
    payload: FlowRunRetentionPolicyReplaceRequest,
    container: FlowRetentionMutationContainer,
) -> FlowRunRetentionPolicySettings:
    return await container.flow_run_retention_policy_service().replace_flow(
        flow_id=flow_id,
        policy=payload.policy,
        reason=payload.reason,
    )


@settings_admin_router.post(
    "/flow-run-retention-policy/purge",
    response_model=FlowRunHistoryPurgePublic,
    operation_id="purge_organization_flow_run_history",
    summary="Preview or purge due Organization Flow run history",
    description=(
        "Administrators can preview or explicitly purge one bounded batch of due "
        "terminal runs under the effective preserve policy, plus expired unbound "
        "live transcripts in the authenticated tenant. The limit applies separately "
        "to runs and transcripts, with separate candidate and deletion counts. "
        "Dry runs select candidates but delete nothing "
        "and emit no audit event. Real purges require an audit row in the same "
        "transaction. Review-required runs, unresolved deliveries and runs under a "
        "legal hold are excluded."
    ),
    responses={
        403: _retention_forbidden_response("manage"),
        409: _flow_retention_lock_busy_response(),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RETENTION_ACCESS_REASON,
)
async def purge_organization_flow_run_history(
    payload: FlowRunHistoryPurgeRequest,
    container: FlowRetentionMutationContainer,
) -> FlowRunHistoryPurgePublic:
    return await container.flow_run_retention_policy_service().purge_due_history(
        dry_run=payload.dry_run, limit=payload.limit
    )


@settings_admin_router.post(
    "/flow-run-retention-policy/spaces/{space_id}/purge",
    response_model=FlowRunHistoryPurgePublic,
    operation_id="purge_space_flow_run_history",
    summary="Preview or purge due Space Flow run history",
    description=(
        "Apply the administrator purge to one Space in the authenticated tenant. "
        "Dry-run is the default and reports candidates without deleting anything. "
        "Real batches delete due terminal runs under the effective preserve policy "
        "and expired unbound live transcripts in this Space, with a transaction audit. "
        "The limit applies separately to runs and transcripts, with separate counts. "
        "Review-required runs, unresolved deliveries and runs under a legal hold "
        "remain stored."
    ),
    responses={
        403: _retention_forbidden_response("manage"),
        404: _flow_retention_not_found_response("Space"),
        409: _flow_retention_lock_busy_response(),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RETENTION_ACCESS_REASON,
)
async def purge_space_flow_run_history(
    space_id: UUID,
    payload: FlowRunHistoryPurgeRequest,
    container: FlowRetentionMutationContainer,
) -> FlowRunHistoryPurgePublic:
    return await container.flow_run_retention_policy_service().purge_due_history(
        space_id=space_id, dry_run=payload.dry_run, limit=payload.limit
    )


@settings_admin_router.post(
    "/flow-run-retention-policy/flows/{flow_id}/purge",
    response_model=FlowRunHistoryPurgePublic,
    operation_id="purge_flow_run_history",
    summary="Preview or purge due Flow run history",
    description=(
        "Apply the administrator purge to one Flow in the authenticated tenant. "
        "Dry-run is the default and reports candidates without deleting anything. "
        "Real batches delete due terminal runs under the effective preserve policy "
        "and expired unbound live transcripts in this Flow, with a transaction audit. "
        "The limit applies separately to runs and transcripts, with separate counts. "
        "Review-required runs, unresolved deliveries and runs under a legal hold "
        "remain stored."
        " A deleted Flow is accepted."
    ),
    responses={
        403: _retention_forbidden_response("manage"),
        404: _flow_retention_not_found_response("Flow"),
        409: _flow_retention_lock_busy_response(),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RETENTION_ACCESS_REASON,
)
async def purge_flow_run_history(
    flow_id: UUID,
    payload: FlowRunHistoryPurgeRequest,
    container: FlowRetentionMutationContainer,
) -> FlowRunHistoryPurgePublic:
    return await container.flow_run_retention_policy_service().purge_due_history(
        flow_id=flow_id, dry_run=payload.dry_run, limit=payload.limit
    )


_FLOW_RETENTION_HOLD_EFFECT = (
    "Until the hold is released or its end date passes, whatever the "
    "Organization, Space or Flow policy says, the explicit purge and the "
    "debug-evidence redaction skip held runs, and the Space cannot be deleted "
    "(space_contains_legal_hold)."
)


@settings_admin_router.get(
    "/flow-retention-holds",
    response_model=FlowRetentionHoldPage,
    operation_id="list_flow_retention_holds",
    summary="List legal holds on Flow run history",
    description=(
        "List the Organization's legal holds, newest first: active ones by default, "
        "or all including released and expired ones, optionally for one Flow. Each "
        "hold names who placed and released it as recorded at that time. "
        + _FLOW_RETENTION_HOLD_EFFECT
    ),
    responses={403: _retention_forbidden_response("view")},
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RETENTION_ACCESS_REASON,
)
async def list_flow_retention_holds(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    status: FlowRetentionHoldStatusFilter = Query(
        default=FlowRetentionHoldStatusFilter.ACTIVE,
        description="active: holds that stop deletion now; all: every hold.",
    ),
    flow_id: UUID | None = Query(default=None, description="Only this Flow's holds."),
    limit: int = Query(default=50, ge=1, le=MAX_FLOW_RETENTION_HOLD_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
) -> FlowRetentionHoldPage:
    return await container.flow_retention_hold_service().list_holds(
        status=status, flow_id=flow_id, limit=limit, offset=offset
    )


@settings_admin_router.post(
    "/flow-retention-holds",
    response_model=FlowRetentionHoldPlacement,
    status_code=201,
    operation_id="place_flow_retention_hold",
    summary="Place a legal hold on Flow run history",
    description=(
        "Hold a whole Flow (every run, including runs created later) or named runs "
        "of it, with a reason, a review date and an optional end date. The review "
        "date never ends the hold: past it, the hold is flagged review overdue "
        "(also in Flow runtime health) until the review is extended or the hold is "
        "released. A deleted Flow can be held. "
        + _FLOW_RETENTION_HOLD_EFFECT
        + " The hold and its required audit event commit together; the request "
        "waits for an open history deletion to finish first."
    ),
    responses={
        400: _settings_error_response(
            description=(
                f"A named run is not a run of the Flow "
                f"(`{FLOW_RETENTION_HOLD_RUN_NOT_IN_FLOW_CODE}`), the end date is "
                f"not in the future (`{FLOW_RETENTION_HOLD_END_NOT_IN_FUTURE_CODE}`), "
                "or the review date is not in the future or beyond "
                "flow_retention_hold_max_review_days "
                f"(`{FLOW_RETENTION_HOLD_REVIEW_OUT_OF_RANGE_CODE}`)."
            ),
            message="Every held run must be a run of the chosen Flow.",
            eneo_error_code=ErrorCodes.BAD_REQUEST,
            code=FLOW_RETENTION_HOLD_RUN_NOT_IN_FLOW_CODE,
        ),
        403: _retention_forbidden_response("holds"),
        404: _flow_retention_not_found_response("Flow"),
        409: _flow_retention_lock_busy_response(),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RETENTION_ACCESS_REASON,
)
async def place_flow_retention_hold(
    payload: FlowRetentionHoldCreateRequest,
    container: FlowRetentionMutationContainer,
) -> FlowRetentionHoldPlacement:
    return await container.flow_retention_hold_service().place(payload)


@settings_admin_router.post(
    "/flow-retention-holds/{hold_id}/extend-review",
    response_model=FlowRetentionHold,
    operation_id="extend_flow_retention_hold_review",
    summary="Extend the review date of a legal hold",
    description=(
        "Move an active hold's review date later, with a reason. The hold keeps "
        "stopping deletion either way; the extension writes its required audit "
        "event (old and new review date, reason) in the same transaction."
    ),
    responses={
        400: _settings_error_response(
            description=(
                "The new review date is not later than the current one "
                f"(`{FLOW_RETENTION_HOLD_REVIEW_NOT_LATER_CODE}`), or not in the "
                "future and within flow_retention_hold_max_review_days "
                f"(`{FLOW_RETENTION_HOLD_REVIEW_OUT_OF_RANGE_CODE}`)."
            ),
            message="The new review date must be later than the current one.",
            eneo_error_code=ErrorCodes.BAD_REQUEST,
            code=FLOW_RETENTION_HOLD_REVIEW_NOT_LATER_CODE,
        ),
        403: _retention_forbidden_response("holds"),
        404: _flow_retention_not_found_response("Legal hold"),
        409: _settings_error_response(
            description=(
                "The hold is released or its end date has passed "
                f"(`{FLOW_RETENTION_HOLD_NOT_ACTIVE_CODE}`), or another retention "
                "change or deletion held the retention lock too long "
                f"(`{_FLOW_RETENTION_LOCK_BUSY_CODE}`)."
            ),
            message="Only an active legal hold can have its review extended.",
            eneo_error_code=ErrorCodes.CONFLICT,
            code=FLOW_RETENTION_HOLD_NOT_ACTIVE_CODE,
        ),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RETENTION_ACCESS_REASON,
)
async def extend_flow_retention_hold_review(
    hold_id: UUID,
    payload: FlowRetentionHoldExtendReviewRequest,
    container: FlowRetentionMutationContainer,
) -> FlowRetentionHold:
    return await container.flow_retention_hold_service().extend_review(
        hold_id=hold_id, request=payload
    )


@settings_admin_router.post(
    "/flow-retention-holds/{hold_id}/release",
    response_model=FlowRetentionHold,
    operation_id="release_flow_retention_hold",
    summary="Release a legal hold on Flow run history",
    description=(
        "Release one hold with a reason. Only this hold's coverage ends: a run "
        "another active hold covers stays held. The released hold stays listed "
        "as part of the record, and the release writes its required audit event "
        "in the same transaction."
    ),
    responses={
        403: _retention_forbidden_response("holds"),
        404: _flow_retention_not_found_response("Legal hold"),
        409: _settings_error_response(
            description=(
                "The hold is already released "
                f"(`{FLOW_RETENTION_HOLD_ALREADY_RELEASED_CODE}`), or another "
                "retention change or deletion held the retention lock too long "
                f"(`{_FLOW_RETENTION_LOCK_BUSY_CODE}`)."
            ),
            message="This legal hold is already released.",
            eneo_error_code=ErrorCodes.CONFLICT,
            code=FLOW_RETENTION_HOLD_ALREADY_RELEASED_CODE,
        ),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RETENTION_ACCESS_REASON,
)
async def release_flow_retention_hold(
    hold_id: UUID,
    payload: FlowRetentionHoldReleaseRequest,
    container: FlowRetentionMutationContainer,
) -> FlowRetentionHold:
    return await container.flow_retention_hold_service().release(
        hold_id=hold_id, reason=payload.reason
    )


@settings_admin_router.get(
    "/flow-run-retention-policy/review-queue",
    response_model=FlowRunRetentionReviewPage,
    operation_id="list_organization_flow_run_retention_review_queue",
    summary="List Flow runs awaiting Organization retention review",
    description=(
        "List terminal Flow runs whose effective review_required policy has reached "
        "its age threshold across the Organization. The bounded page contains only "
        "identifiers, names, lifecycle dates, and policy facts; it never returns run "
        "inputs or outputs. Reading this queue does not approve or delete anything."
    ),
    responses={
        400: _flow_retention_invalid_cursor_response(),
        403: _retention_forbidden_response("manage"),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RETENTION_ACCESS_REASON,
)
async def list_organization_flow_run_retention_review_queue(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(
        default=None,
        max_length=512,
        description="Opaque cursor returned as next_cursor by the previous page.",
    ),
) -> FlowRunRetentionReviewPage:
    return await container.flow_run_retention_policy_service().list_organization_review_queue(
        limit=limit,
        cursor=_flow_retention_review_cursor(cursor),
    )


@settings_admin_router.get(
    "/flow-run-retention-policy/spaces/{space_id}/review-queue",
    response_model=FlowRunRetentionReviewPage,
    operation_id="list_space_flow_run_retention_review_queue",
    summary="List Flow runs awaiting retention review in a Space",
    description=(
        "List terminal Flow runs in one Space whose effective review_required policy "
        "has reached its age threshold. A Flow-level preserve override is excluded, "
        "even when the surrounding Space requires review. The bounded response omits "
        "run content, and reading it never approves or deletes data."
    ),
    responses={
        400: _flow_retention_invalid_cursor_response(),
        403: _retention_forbidden_response("manage"),
        404: _flow_retention_not_found_response("Space"),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RETENTION_ACCESS_REASON,
)
async def list_space_flow_run_retention_review_queue(
    space_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(
        default=None,
        max_length=512,
        description="Opaque cursor returned as next_cursor by the previous page.",
    ),
) -> FlowRunRetentionReviewPage:
    return await container.flow_run_retention_policy_service().list_space_review_queue(
        space_id=space_id,
        limit=limit,
        cursor=_flow_retention_review_cursor(cursor),
    )


@settings_admin_router.get(
    "/flow-run-retention-policy/flows/{flow_id}/review-queue",
    response_model=FlowRunRetentionReviewPage,
    operation_id="list_flow_run_retention_review_queue",
    summary="List runs awaiting retention review for one Flow",
    description=(
        "List terminal runs for one Flow whose effective review_required policy has "
        "reached its age threshold, including a policy inherited from its Space or "
        "Organization. The bounded response deliberately omits inputs and outputs. "
        "Reading it is side-effect free and cannot approve or delete run history."
        " A deleted Flow is accepted."
    ),
    responses={
        400: _flow_retention_invalid_cursor_response(),
        403: _retention_forbidden_response("manage"),
        404: _flow_retention_not_found_response("Flow"),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RETENTION_ACCESS_REASON,
)
async def list_flow_run_retention_review_queue(
    flow_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(
        default=None,
        max_length=512,
        description="Opaque cursor returned as next_cursor by the previous page.",
    ),
) -> FlowRunRetentionReviewPage:
    return await container.flow_run_retention_policy_service().list_flow_review_queue(
        flow_id=flow_id,
        limit=limit,
        cursor=_flow_retention_review_cursor(cursor),
    )


@settings_admin_router.get(
    "/ai-builder-budget",
    response_model=AIBuilderBudgetSettingsPublic,
    summary="Get AI Builder resource budget settings",
    description=(
        "Return effective prompt reserves, message and attachment limits, "
        "template-inspection limits, and their fixed system ceilings."
    ),
    responses={403: _flow_settings_admin_forbidden_response()},
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def get_ai_builder_budget_settings(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> AIBuilderBudgetSettingsPublic:
    service = cast(_FlowSettingsServiceProtocol, container.settings_service())
    return await service.get_ai_builder_budget_settings()


@settings_admin_router.patch(
    "/ai-builder-budget",
    response_model=AIBuilderBudgetSettingsPublic,
    summary="Update AI Builder resource budget settings",
    description=(
        "Update tenant-owned prompt reserves, message and attachment limits, "
        "and template-inspection limits."
    ),
    responses={
        400: _flow_settings_invalid_payload_response(
            "Invalid AI Builder settings payload.",
            "At least one AI Builder setting must be provided.",
        ),
        403: _flow_settings_admin_forbidden_response(),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def update_ai_builder_budget_settings(
    payload: AIBuilderBudgetSettingsUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> AIBuilderBudgetSettingsPublic:
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
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
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
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
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
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
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
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def update_api_key_expiry_notifications_setting(
    data: ToggleSettingUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.settings_service()
    return await service.update_api_key_expiry_notifications_setting(
        enabled=data.enabled
    )


@settings_admin_router.patch(
    "/whats-new",
    response_model=SettingsPublic,
    responses=responses.get_responses([403]),
    summary="Toggle the What's new feature",
    description="""
Toggle the What's new page, release announcement and menu indicator for your tenant.

**Admin Only:** Requires admin permissions.

**Behavior:**
- Updates the `whats_new_enabled` feature flag for your tenant
- When disabled: the page, the one-time release announcement and the menu indicator are hidden for every user in the tenant
- Change takes effect on the next page load
    """,
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_TENANT_SETTINGS_ADMIN_ACCESS_REASON,
)
async def update_whats_new_setting(
    data: ToggleSettingUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.settings_service()
    return await service.update_whats_new_setting(enabled=data.enabled)
