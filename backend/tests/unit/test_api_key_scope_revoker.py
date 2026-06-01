from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.audit.domain.action_types import ActionType
from intric.authentication.api_key_scope_revoker import ApiKeyScopeRevoker
from intric.authentication.auth_models import (
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyStateReasonCode,
    ApiKeyV2InDB,
)
from tests.unit.api_key_test_utils import make_api_key_with_timestamp


def _make_key(**overrides: object) -> ApiKeyV2InDB:
    return make_api_key_with_timestamp(
        default_permission=ApiKeyPermission.WRITE,
        scope_type=ApiKeyScopeType.ASSISTANT,
        scope_id=uuid4(),
        **overrides,
    )


@pytest.mark.asyncio
async def test_scope_revoker_updates_and_audits():
    key = _make_key()
    repo = AsyncMock()
    repo.list_by_scope.return_value = [key]
    repo.update.return_value = key
    audit = AsyncMock()
    user = SimpleNamespace(id=uuid4(), tenant_id=key.tenant_id)

    revoker = ApiKeyScopeRevoker(repo, audit, user)
    revoked = await revoker.revoke_scope(
        scope_type=ApiKeyScopeType.ASSISTANT,
        scope_id=key.scope_id,
        reason_code=ApiKeyStateReasonCode.SCOPE_REMOVED,
        reason_text="Assistant deleted",
    )

    assert revoked == 1
    repo.update.assert_awaited()
    assert (
        repo.update.call_args.kwargs["revoked_reason_code"]
        == ApiKeyStateReasonCode.SCOPE_REMOVED.value
    )
    audit.log_async.assert_awaited()
    assert audit.log_async.call_args.kwargs["action"] == ActionType.API_KEY_REVOKED
