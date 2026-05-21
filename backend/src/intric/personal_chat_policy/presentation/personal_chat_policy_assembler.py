# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from intric.personal_chat_policy.domain.personal_chat_policy import (
    PersonalChatPolicy,
)
from intric.personal_chat_policy.presentation.personal_chat_policy_models import (
    McpRestrictionPublic,
    ModelsRestrictionPublic,
    PersonalChatPolicyPublic,
    PolicyCompletionModelPublic,
    PromptEnforcementPublic,
)


class PersonalChatPolicyAssembler:
    @staticmethod
    def to_public(policy: PersonalChatPolicy) -> PersonalChatPolicyPublic:
        return PersonalChatPolicyPublic(
            models_restriction=ModelsRestrictionPublic(
                enabled=policy.models_restriction_enabled,
                models=[
                    PolicyCompletionModelPublic(
                        completion_model_id=m.completion_model_id,
                        is_default=m.is_default,
                    )
                    for m in policy.completion_models
                ],
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
