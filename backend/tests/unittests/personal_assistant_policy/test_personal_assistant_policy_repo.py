from unittest.mock import AsyncMock
from uuid import uuid4

from intric.personal_assistant_policy.domain.personal_assistant_policy import (
    PersonalAssistantPolicy,
)
from intric.personal_assistant_policy.infrastructure.personal_assistant_policy_repo_impl import (
    PersonalAssistantPolicyRepoImpl,
)


async def test_create_empty_returns_existing_policy_when_insert_conflicts():
    tenant_id = uuid4()
    existing = PersonalAssistantPolicy(id=uuid4(), tenant_id=tenant_id)

    repo = PersonalAssistantPolicyRepoImpl(session=AsyncMock())
    repo.session.scalar = AsyncMock(return_value=None)
    repo.get_by_tenant = AsyncMock(return_value=existing)  # type: ignore[method-assign]

    result = await repo.create_empty(tenant_id)

    assert result is existing
