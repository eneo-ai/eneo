# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Protocol
from uuid import UUID

from intric.governance_policy.domain.governance_policy import (
    GovernancePolicy,
    PolicyScope,
)


class GovernancePolicyRepo(Protocol):
    # The repo is scope-agnostic: callers in the application layer decide which
    # scope applies to the context at hand (today always PERSONAL_DEFAULT_ASSISTANT).
    # When a second scope is introduced this is the seam that stays put — only
    # the callers gain scope-selection logic, not the persistence layer.
    async def get_by_tenant(
        self, tenant_id: UUID, *, scope: PolicyScope
    ) -> GovernancePolicy | None: ...

    async def get_by_tenant_for_update(
        self, tenant_id: UUID, *, scope: PolicyScope
    ) -> GovernancePolicy | None: ...

    async def create_empty(
        self, tenant_id: UUID, *, scope: PolicyScope
    ) -> GovernancePolicy: ...

    async def save(
        self,
        policy: GovernancePolicy,
        *,
        updated_by_user_id: UUID,
    ) -> GovernancePolicy: ...

    async def get_by_prompt_library_id(
        self, *, tenant_id: UUID, prompt_library_id: UUID
    ) -> GovernancePolicy | None:
        """Return the policy that references the given prompt library entry,
        or None. Used by PromptLibraryService.delete() to produce a friendly
        409 instead of a raw FK violation."""
