# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Protocol
from uuid import UUID

from intric.personal_chat_policy.domain.personal_chat_policy import PersonalChatPolicy


class PersonalChatPolicyRepo(Protocol):
    async def get_by_tenant(self, tenant_id: UUID) -> PersonalChatPolicy | None: ...

    async def create_empty(self, tenant_id: UUID) -> PersonalChatPolicy: ...

    async def save(
        self,
        policy: PersonalChatPolicy,
        *,
        updated_by_user_id: UUID,
    ) -> PersonalChatPolicy: ...

    async def get_by_prompt_library_id(
        self, *, tenant_id: UUID, prompt_library_id: UUID
    ) -> PersonalChatPolicy | None:
        """Return the policy that references the given prompt library entry,
        or None. Used by PromptLibraryService.delete() to produce a friendly
        409 instead of a raw FK violation."""
