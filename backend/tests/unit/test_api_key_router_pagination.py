"""Unit tests for post-filter API key pagination behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.authentication.api_key_router import _collect_manageable_keys_for_page
from intric.authentication.api_key_resolver import ApiKeyValidationError
from intric.authentication.auth_models import ApiKeyScopeType
from tests.unit.api_key_test_utils import make_api_key


def _key(name: str, created_at: datetime):
    return make_api_key(
        name=name,
        created_at=created_at,
        scope_type=ApiKeyScopeType.SPACE,
        scope_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_collect_manageable_keys_fetches_next_batch_when_first_batch_underfills():
    now = datetime.now(timezone.utc)
    batch_one = [
        _key("k1", now - timedelta(seconds=1)),
        _key("k2", now - timedelta(seconds=2)),
        _key("k3", now - timedelta(seconds=3)),
    ]
    batch_two = [
        _key("k4", now - timedelta(seconds=4)),
        _key("k5", now - timedelta(seconds=5)),
        _key("k6", now - timedelta(seconds=6)),
    ]

    allowed_ids = {
        batch_one[2].id,
        batch_two[0].id,
        batch_two[1].id,
    }

    repo = AsyncMock()
    repo.list_paginated = AsyncMock(side_effect=[batch_one, batch_two])

    policy = AsyncMock()

    async def _authorize(*, key):
        if key.id not in allowed_ids:
            raise ApiKeyValidationError(
                status_code=403,
                code="insufficient_permission",
                message="forbidden",
            )

    policy.ensure_manage_authorized = AsyncMock(side_effect=_authorize)

    result = await _collect_manageable_keys_for_page(
        repo=repo,
        policy=policy,
        tenant_id=batch_one[0].tenant_id,
        limit=2,
        cursor=None,
        scope_type=None,
        scope_id=None,
        state=None,
        key_type=None,
    )

    assert len(result) == 3  # limit + 1 manageable entries for cursor pagination
    assert [item.id for item in result] == [
        batch_one[2].id,
        batch_two[0].id,
        batch_two[1].id,
    ]
    assert repo.list_paginated.await_count == 2
    second_call = repo.list_paginated.await_args_list[1].kwargs
    assert second_call["cursor"] == batch_one[-1].created_at


@pytest.mark.asyncio
async def test_collect_manageable_keys_stops_when_raw_batch_exhausted():
    now = datetime.now(timezone.utc)
    batch = [
        _key("k1", now - timedelta(seconds=1)),
        _key("k2", now - timedelta(seconds=2)),
    ]

    repo = AsyncMock()
    repo.list_paginated = AsyncMock(return_value=batch)

    policy = AsyncMock()
    policy.ensure_manage_authorized = AsyncMock(return_value=None)

    result = await _collect_manageable_keys_for_page(
        repo=repo,
        policy=policy,
        tenant_id=batch[0].tenant_id,
        limit=2,
        cursor=None,
        scope_type=None,
        scope_id=None,
        state=None,
        key_type=None,
    )

    assert [item.id for item in result] == [batch[0].id, batch[1].id]
    assert repo.list_paginated.await_count == 1
