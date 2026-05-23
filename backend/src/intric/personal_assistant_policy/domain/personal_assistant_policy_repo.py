# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Protocol
from uuid import UUID

from intric.personal_assistant_policy.domain.personal_assistant_policy import (
    PersonalAssistantPolicy,
)


class PersonalAssistantPolicyRepo(Protocol):
    async def get_by_tenant(
        self, tenant_id: UUID
    ) -> PersonalAssistantPolicy | None: ...

    async def create_empty(self, tenant_id: UUID) -> PersonalAssistantPolicy: ...

    async def save(
        self,
        policy: PersonalAssistantPolicy,
        *,
        updated_by_user_id: UUID,
    ) -> PersonalAssistantPolicy: ...

    async def get_by_prompt_library_id(
        self, *, tenant_id: UUID, prompt_library_id: UUID
    ) -> PersonalAssistantPolicy | None:
        """Return the policy that references the given prompt library entry,
        or None. Used by PromptLibraryService.delete() to produce a friendly
        409 instead of a raw FK violation."""
