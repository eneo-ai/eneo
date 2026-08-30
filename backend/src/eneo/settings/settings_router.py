from typing import Annotated, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eneo.authentication import auth_dependencies
from eneo.files.mime_support import supported_mimes
from eneo.flows.domain.flow_run_retention_policy import (
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
    settings: SettingsBase,
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
    container: Annotated[
        Container,
        Depends(get_container(with_user=True, with_upload_admission=True)),
    ],
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
    container: Annotated[
        Container,
        Depends(get_container(with_user=True, with_upload_admission=True)),
    ],
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
async def get_mapped_execution_policy(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowMappedExecutionPolicyPublic:
    validate_permission(container.user(), Permission.ADMIN)
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
async def update_mapped_execution_policy(
    payload: FlowMappedExecutionPolicyUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowMappedExecutionPolicyPublic:
    validate_permission(container.user(), Permission.ADMIN)
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
async def get_rag_evidence_policy(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowRagEvidencePolicyPublic:
    validate_permission(container.user(), Permission.ADMIN)
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
async def update_rag_evidence_policy(
    payload: FlowRagEvidencePolicyUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowRagEvidencePolicyPublic:
    validate_permission(container.user(), Permission.ADMIN)
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
        "Return the independent eligibility windows for stored Flow debug evidence "
        "and abandoned runtime uploads. Flow run-history retention is configured "
        "through the dedicated hierarchical policy endpoints. Reading this endpoint "
        "never previews, deletes, or redacts Flow data."
    ),
    responses={403: _flow_settings_admin_forbidden_response()},
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
    operation_id="update_flow_retention_policy",
    summary="Update flow retention policy",
    description=(
        "Update the independent eligibility windows for stored Flow debug evidence "
        "and abandoned runtime uploads. Omitted fields are unchanged and null removes "
        "the tenant input. Saving these values never deletes or redacts Flow data."
    ),
    responses={
        400: _flow_settings_invalid_payload_response(
            "Invalid flow retention policy payload.",
            "At least one flow retention policy field must be provided.",
        ),
        403: _flow_settings_admin_forbidden_response(),
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
    "/flow-run-retention-policy",
    response_model=FlowRunRetentionPolicySettings,
    operation_id="get_organization_flow_run_retention_policy",
    summary="Get the Organization Flow run-history retention policy",
    description=(
        "Return the Organization default and its effective Flow run-history policy. "
        "No configured policy means run history has no age threshold and remains stored."
    ),
    responses={403: _flow_settings_admin_forbidden_response()},
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
        "Replace the complete Organization policy or clear it. The initial modes "
        "either preserve eligible data for explicit administrator purge or require "
        "human review; neither mode deletes data automatically."
    ),
    responses={403: _flow_settings_admin_forbidden_response()},
)
async def replace_organization_flow_run_retention_policy(
    payload: FlowRunRetentionPolicyReplaceRequest,
    container: FlowRetentionMutationContainer,
) -> FlowRunRetentionPolicySettings:
    return await container.flow_run_retention_policy_service().replace_organization(
        policy=payload.policy
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
    responses={403: _flow_settings_admin_forbidden_response()},
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
        "List active Flows in one Organization-scoped Space, including Flows the "
        "Organization administrator cannot discover through membership-scoped Flow "
        "authoring APIs. The bounded response contains identifiers and names only."
    ),
    responses={
        403: _flow_settings_admin_forbidden_response(),
        404: _flow_retention_not_found_response("Space"),
    },
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
        403: _flow_settings_admin_forbidden_response(),
        404: _flow_retention_not_found_response("Space"),
    },
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
        "conversation or AI Builder retention, and it never schedules deletion."
    ),
    responses={
        403: _flow_settings_admin_forbidden_response(),
        404: _flow_retention_not_found_response("Space"),
    },
)
async def replace_space_flow_run_retention_policy(
    space_id: UUID,
    payload: FlowRunRetentionPolicyReplaceRequest,
    container: FlowRetentionMutationContainer,
) -> FlowRunRetentionPolicySettings:
    return await container.flow_run_retention_policy_service().replace_space(
        space_id=space_id,
        policy=payload.policy,
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
    ),
    responses={
        403: _flow_settings_admin_forbidden_response(),
        404: _flow_retention_not_found_response("Flow"),
    },
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
        "does not mutate the published definition. The initial modes require a later "
        "explicit administrator action; saving this policy never schedules deletion."
    ),
    responses={
        403: _flow_settings_admin_forbidden_response(),
        404: _flow_retention_not_found_response("Flow"),
    },
)
async def replace_flow_run_retention_policy(
    flow_id: UUID,
    payload: FlowRunRetentionPolicyReplaceRequest,
    container: FlowRetentionMutationContainer,
) -> FlowRunRetentionPolicySettings:
    return await container.flow_run_retention_policy_service().replace_flow(
        flow_id=flow_id,
        policy=payload.policy,
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
        403: _flow_settings_admin_forbidden_response(),
    },
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
        403: _flow_settings_admin_forbidden_response(),
        404: _flow_retention_not_found_response("Space"),
    },
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
    ),
    responses={
        400: _flow_retention_invalid_cursor_response(),
        403: _flow_settings_admin_forbidden_response(),
        404: _flow_retention_not_found_response("Flow"),
    },
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
async def get_ai_builder_budget_settings(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> AIBuilderBudgetSettingsPublic:
    validate_permission(container.user(), Permission.ADMIN)
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
