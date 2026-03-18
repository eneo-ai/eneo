from unittest.mock import MagicMock

import pytest

from intric.main.exceptions import UnauthorizedException
from intric.roles.permissions import (
    Permission,
    has_permission,
    validate_permission,
    validate_permissions,
)
from intric.users.user import UserInDB


class MockService:
    def __init__(self, user: UserInDB):
        self.user = user

    @validate_permissions(Permission.ADMIN)
    async def func_in_need_of_validation(self, *args, **kwargs):
        # Dangerous things that we need to validate against

        1 / 0


async def test_validation_decorator():
    user = MagicMock(permissions=[Permission.ADMIN])

    service = MockService(user)

    with pytest.raises(ZeroDivisionError):
        await service.func_in_need_of_validation(3, 10, two=4)

    user.permissions = [Permission.AI]

    with pytest.raises(
        UnauthorizedException,
        match=f"Need permission {Permission.ADMIN.value} in order to access",
    ):
        await service.func_in_need_of_validation(45, "thing")


def test_flow_granular_permissions_accept_legacy_flows_permission():
    permissions = [Permission.FLOWS]

    assert has_permission(permissions, Permission.FLOWS_VIEW) is True
    assert has_permission(permissions, Permission.FLOWS_RUN) is True
    assert has_permission(permissions, Permission.FLOWS_MANAGE) is True
    assert has_permission(permissions, Permission.FLOWS_AI_BUILDER) is True


def test_legacy_flows_permission_is_not_implied_by_granular_permissions():
    permissions = [Permission.FLOWS_VIEW, Permission.FLOWS_RUN, Permission.FLOWS_MANAGE]

    assert has_permission(permissions, Permission.FLOWS) is False


def test_validate_permission_rejects_user_without_required_granular_flow_permission():
    user = MagicMock(permissions=[Permission.FLOWS_VIEW])

    with pytest.raises(
        UnauthorizedException,
        match=f"Need permission {Permission.FLOWS_MANAGE.value} in order to access",
    ):
        validate_permission(user, Permission.FLOWS_MANAGE)
