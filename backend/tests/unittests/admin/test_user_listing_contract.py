from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.admin.admin_models import AdminUsersQueryParams, StateFilter
from eneo.admin.admin_service import AdminService
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleInDB
from eneo.users.user import PaginatedResult, SearchFilters


def test_role_filter_is_a_validated_uuid():
    role_id = uuid4()
    assert AdminUsersQueryParams(role_id=str(role_id)).role_id == role_id
    assert SearchFilters(role_id=role_id).has_filters()
    with pytest.raises(ValidationError):
        AdminUsersQueryParams(role_id="invalid")


@pytest.mark.parametrize("total_count", [10001, 50000])
def test_large_lists_stop_at_the_last_reachable_page(total_count):
    result = PaginatedResult(items=[], total_count=total_count, page=100, page_size=100)
    assert result.total_count == total_count
    assert result.total_pages == 100
    assert not result.has_next
    assert result.has_previous


@pytest.mark.parametrize("state", [StateFilter.ACTIVE, StateFilter.INACTIVE])
async def test_admin_listing_preserves_filters_and_counts(user, state):
    role_id = uuid4()
    user.roles = [
        RoleInDB(
            id=uuid4(),
            name="Admin",
            permissions=[Permission.ADMIN],
            tenant_id=user.tenant_id,
        )
    ]
    counts = {"active": 12345, "inactive": 23456}
    repo = AsyncMock()
    repo.get_paginated.return_value = PaginatedResult(
        items=[],
        total_count=counts[state.value],
        page=100,
        page_size=100,
        counts=counts,
    )
    service = AdminService(
        user=user, user_repo=repo, tenant_service=AsyncMock(), user_service=AsyncMock()
    )
    response = await service.list_users_paginated(
        AdminUsersQueryParams(
            page=100,
            search_email=" example.com ",
            search_name=" anna ",
            state_filter=state,
            role_id=role_id,
        )
    )
    args = repo.get_paginated.call_args.kwargs
    assert args["tenant_id"] == user.tenant_id
    assert args["search"] == SearchFilters(
        email="example.com", name="anna", state_filter=state.value, role_id=role_id
    )
    assert response.metadata.total_count == counts[state.value]
    assert response.metadata.counts == counts
    assert response.metadata.total_pages == 100
    assert not response.metadata.has_next
