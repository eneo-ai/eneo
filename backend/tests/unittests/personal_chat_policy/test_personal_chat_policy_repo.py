from unittest.mock import AsyncMock
from uuid import uuid4

from intric.personal_chat_policy.domain.personal_chat_policy import PersonalChatPolicy
from intric.personal_chat_policy.infrastructure.personal_chat_policy_repo_impl import (
    PersonalChatPolicyRepoImpl,
)


async def test_create_empty_returns_existing_policy_when_insert_conflicts():
    tenant_id = uuid4()
    existing = PersonalChatPolicy(id=uuid4(), tenant_id=tenant_id)

    repo = PersonalChatPolicyRepoImpl(session=AsyncMock())
    repo.session.scalar = AsyncMock(return_value=None)
    repo.get_by_tenant = AsyncMock(return_value=existing)  # type: ignore[method-assign]

    result = await repo.create_empty(tenant_id)

    assert result is existing
