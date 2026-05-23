# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from intric.personal_assistant_policy.domain.personal_assistant_policy import (
    PersonalAssistantPolicy,
)
from intric.personal_assistant_policy.presentation.personal_assistant_policy_models import (
    McpRestrictionPublic,
    ModelsRestrictionPublic,
    PersonalAssistantPolicyPublic,
    PolicyCompletionModelPublic,
    PromptEnforcementPublic,
)


class PersonalAssistantPolicyAssembler:
    @staticmethod
    def to_public(policy: PersonalAssistantPolicy) -> PersonalAssistantPolicyPublic:
        return PersonalAssistantPolicyPublic(
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
                server_ids=list(policy.mcp_server_ids),
            ),
            prompt_enforcement=PromptEnforcementPublic(
                enabled=policy.prompt_enforcement_enabled,
                prompt_library_id=policy.default_prompt_library_id,
            ),
            updated_at=policy.updated_at,
            updated_by_user_id=policy.updated_by_user_id,
        )
