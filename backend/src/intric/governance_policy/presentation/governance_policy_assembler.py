# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from intric.governance_policy.domain.governance_policy import (
    GovernancePolicy,
)
from intric.governance_policy.presentation.governance_policy_models import (
    GovernancePolicyPublic,
    McpRestrictionPublic,
    ModelsRestrictionPublic,
    PolicyCompletionModelPublic,
    PolicyMcpServerPublic,
    PromptEnforcementPublic,
)


class GovernancePolicyAssembler:
    @staticmethod
    def to_public(policy: GovernancePolicy) -> GovernancePolicyPublic:
        return GovernancePolicyPublic(
            models_restriction=ModelsRestrictionPublic(
                enabled=policy.models_restriction_enabled,
                models=[
                    PolicyCompletionModelPublic(
                        completion_model_id=m.completion_model_id,
                        is_default=m.is_default,
                    )
                    for m in policy.completion_models
                ],
                provider_ids=list(policy.model_provider_ids),
            ),
            mcp_restriction=McpRestrictionPublic(
                enabled=policy.mcp_restriction_enabled,
                servers=[
                    PolicyMcpServerPublic(
                        mcp_server_id=s.mcp_server_id,
                        is_default_enabled=s.is_default_enabled,
                    )
                    for s in policy.mcp_servers
                ],
                disabled_tool_ids=list(policy.disabled_mcp_tool_ids),
            ),
            prompt_enforcement=PromptEnforcementPublic(
                enabled=policy.prompt_enforcement_enabled,
                prompt_library_id=policy.default_prompt_library_id,
            ),
            updated_at=policy.updated_at,
            updated_by_user_id=policy.updated_by_user_id,
        )
