from unittest.mock import MagicMock

import pytest

from eneo.main.exceptions import UnauthorizedException
from eneo.roles.permissions import Permission, validate_permissions
from eneo.users.user import UserInDB


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
