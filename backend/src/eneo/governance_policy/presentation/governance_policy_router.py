# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Annotated, Iterable
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.governance_policy.domain.governance_policy import (
    GovernancePolicy,
    PolicyCompletionModel,
    PolicyMcpServer,
)
from eneo.governance_policy.presentation.governance_policy_models import (
    GovernancePolicyPublic,
    GovernancePolicyUpdate,
)
from eneo.main.container.container import Container
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.skills.domain.skill import ResolvedSkillBinding
from eneo.skills.presentation.skill_assembler import (
    skill_binding_audit_entries,
    skill_binding_references_from_input,
)

router = APIRouter()

_ContainerWithUser = Annotated[Container, Depends(get_container(with_user=True))]


def _ids(ids: Iterable[UUID]) -> list[str]:
    return sorted(str(id) for id in ids)


def _policy_changes(
    before: GovernancePolicy,
    after: GovernancePolicy,
    *,
    before_skills: list[ResolvedSkillBinding],
    after_skills: list[ResolvedSkillBinding],
) -> dict[str, object]:
    changes: dict[str, object] = {}

    def _model_entries(policy: GovernancePolicy) -> list[dict[str, object]]:
        # Sort by id so a reordered-but-identical model set is not logged as a
        # change — the request order and the stored row order need not match.
        return sorted(
            (
                {"id": str(m.completion_model_id), "is_default": m.is_default}
                for m in policy.completion_models
            ),
            key=lambda entry: str(entry["id"]),
        )

    before_models = _model_entries(before)
    after_models = _model_entries(after)
    if before.models_restriction_enabled != after.models_restriction_enabled:
        changes["models_restriction_enabled"] = {
            "old": before.models_restriction_enabled,
            "new": after.models_restriction_enabled,
        }
    if before_models != after_models:
        changes["completion_models"] = {"old": before_models, "new": after_models}
    if _ids(before.model_provider_ids) != _ids(after.model_provider_ids):
        changes["model_provider_ids"] = {
            "old": _ids(before.model_provider_ids),
            "new": _ids(after.model_provider_ids),
        }
    if before.mcp_restriction_enabled != after.mcp_restriction_enabled:
        changes["mcp_restriction_enabled"] = {
            "old": before.mcp_restriction_enabled,
            "new": after.mcp_restriction_enabled,
        }

    def _mcp_entries(policy: GovernancePolicy) -> list[dict[str, object]]:
        return sorted(
            (
                {
                    "id": str(s.mcp_server_id),
                    "is_default_enabled": s.is_default_enabled,
                }
                for s in policy.mcp_servers
            ),
            key=lambda entry: str(entry["id"]),
        )

    before_mcp = _mcp_entries(before)
    after_mcp = _mcp_entries(after)
    if before_mcp != after_mcp:
        changes["mcp_servers"] = {"old": before_mcp, "new": after_mcp}
    if _ids(before.disabled_mcp_tool_ids) != _ids(after.disabled_mcp_tool_ids):
        changes["disabled_mcp_tool_ids"] = {
            "old": _ids(before.disabled_mcp_tool_ids),
            "new": _ids(after.disabled_mcp_tool_ids),
        }
    if before.prompt_enforcement_enabled != after.prompt_enforcement_enabled:
        changes["prompt_enforcement_enabled"] = {
            "old": before.prompt_enforcement_enabled,
            "new": after.prompt_enforcement_enabled,
        }
    if before.default_prompt_library_id != after.default_prompt_library_id:
        changes["default_prompt_library_id"] = {
            "old": str(before.default_prompt_library_id)
            if before.default_prompt_library_id
            else None,
            "new": str(after.default_prompt_library_id)
            if after.default_prompt_library_id
            else None,
        }

    before_skill_entries = skill_binding_audit_entries(before_skills)
    after_skill_entries = skill_binding_audit_entries(after_skills)
    if before_skill_entries != after_skill_entries:
        changes["skills"] = {
            "old": before_skill_entries,
            "new": after_skill_entries,
        }

    return changes


@router.get(
    "/",
    response_model=GovernancePolicyPublic,
    responses=responses.get_responses([403]),
)
async def get_governance_policy(container: _ContainerWithUser):
    service = container.governance_policy_service()
    assembler = container.governance_policy_assembler()
    policy = await service.get_policy()
    skill_bindings = await service.get_skill_bindings(policy)
    return assembler.to_public(policy, skill_bindings)


@router.put(
    "/",
    response_model=GovernancePolicyPublic,
    responses=responses.get_responses([400, 403]),
    description="Update the personal assistant governance policy",
)
async def update_governance_policy(
    payload: GovernancePolicyUpdate,
    request: Request,
    container: _ContainerWithUser,
):
    if (
        payload.skills is not None
        and getattr(request.state, "api_key", None) is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Skill policy changes require a session token.",
        )

    service = container.governance_policy_service()
    assembler = container.governance_policy_assembler()
    before = await service.get_policy_for_update()
    before_skills = await service.get_skill_bindings(before)

    models_restriction = None
    if payload.models_restriction is not None:
        models_restriction = (
            payload.models_restriction.enabled,
            [
                PolicyCompletionModel(
                    completion_model_id=m.completion_model_id,
                    is_default=m.is_default,
                )
                for m in payload.models_restriction.models
            ],
            list(payload.models_restriction.provider_ids),
        )

    mcp_restriction = None
    if payload.mcp_restriction is not None:
        mcp_restriction = (
            payload.mcp_restriction.enabled,
            [
                PolicyMcpServer(
                    mcp_server_id=s.mcp_server_id,
                    is_default_enabled=s.is_default_enabled,
                )
                for s in payload.mcp_restriction.servers
            ],
            list(payload.mcp_restriction.disabled_tool_ids),
        )

    prompt_enforcement = None
    if payload.prompt_enforcement is not None:
        prompt_enforcement = (
            payload.prompt_enforcement.enabled,
            payload.prompt_enforcement.prompt_library_id,
        )

    skill_references = None
    if payload.skills is not None:
        skill_references = skill_binding_references_from_input(payload.skills.bindings)

    policy = await service.update_policy(
        models_restriction=models_restriction,
        mcp_restriction=mcp_restriction,
        prompt_enforcement=prompt_enforcement,
        skill_references=skill_references,
    )
    if (
        models_restriction is not None
        or prompt_enforcement is not None
        or skill_references is not None
    ):
        assistant_service = container.assistant_service()
        await assistant_service.assert_personal_default_governance_context_fit()
    assert policy.id is not None
    after_skills = await service.get_skill_bindings(policy)
    changes = _policy_changes(
        before,
        policy,
        before_skills=before_skills,
        after_skills=after_skills,
    )
    if changes:
        user = container.user()
        await container.audit_service().log_async(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.GOVERNANCE_POLICY_UPDATED,
            entity_type=EntityType.GOVERNANCE_POLICY,
            entity_id=policy.id,
            description="Updated personal assistant governance policy",
            metadata=AuditMetadata.standard(
                actor=user,
                target=policy,
                changes=changes,
                extra={"scope": policy.scope.value},
            ),
        )
    return assembler.to_public(policy, after_skills)
