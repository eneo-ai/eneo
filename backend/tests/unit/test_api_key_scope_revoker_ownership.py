from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.authentication.api_key_scope_revoker import ApiKeyScopeRevoker
from eneo.authentication.auth_models import (
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyStateReasonCode,
)
from tests.unit.api_key_test_utils import make_api_key_with_timestamp


def _make_key(**overrides: object):
    return make_api_key_with_timestamp(
        default_permission=ApiKeyPermission.WRITE,
        scope_type=ApiKeyScopeType.ASSISTANT,
        scope_id=uuid4(),
        **overrides,
    )


@pytest.mark.asyncio
async def test_revoke_by_owner_filters_user_ownership():
    """revoke_by_owner should call list_filtered with ownership='user'."""
    tenant_id = uuid4()
    owner_id = uuid4()
    key = _make_key(tenant_id=tenant_id, owner_user_id=owner_id)

    repo = AsyncMock()
    repo.list_filtered.return_value = [key]
    repo.update.return_value = key
    audit = AsyncMock()
    user = SimpleNamespace(id=owner_id, tenant_id=tenant_id)

    revoker = ApiKeyScopeRevoker(repo, audit, user)
    await revoker.revoke_by_owner(
        tenant_id=tenant_id,
        owner_user_id=owner_id,
        reason_code=ApiKeyStateReasonCode.USER_OFFBOARDING,
        reason_text="User removed",
    )

    repo.list_filtered.assert_awaited_once()
    assert repo.list_filtered.call_args.kwargs["ownership"] == "user"


@pytest.mark.asyncio
async def test_revoke_member_keys_filters_user_ownership():
    """All list_filtered calls in revoke_member_keys should include ownership='user'."""
    tenant_id = uuid4()
    owner_id = uuid4()
    space_id = uuid4()
    assistant_id = uuid4()
    app_id = uuid4()

    repo = AsyncMock()
    repo.list_filtered.return_value = []
    audit = AsyncMock()
    user = SimpleNamespace(id=owner_id, tenant_id=tenant_id)

    revoker = ApiKeyScopeRevoker(repo, audit, user)
    await revoker.revoke_member_keys(
        tenant_id=tenant_id,
        owner_user_id=owner_id,
        space_id=space_id,
        assistant_ids=[assistant_id],
        app_ids=[app_id],
        reason_code=ApiKeyStateReasonCode.SCOPE_REMOVED,
        reason_text="Member removed from space",
    )

    # Should have 3 calls: space, assistant, app
    assert repo.list_filtered.await_count == 3
    for call in repo.list_filtered.call_args_list:
        assert call.kwargs["ownership"] == "user", (
            f"Expected ownership='user' in call kwargs: {call.kwargs}"
        )
