"""A competing JIT insert must not abort the request's outer transaction."""

import pytest
import sqlalchemy as sa

from eneo.database.tables.users_table import Users
from eneo.main.exceptions import UniqueException
from eneo.users.user import UserAdd, UserState


@pytest.mark.integration
async def test_duplicate_user_insert_preserves_outer_transaction(
    db_container, admin_user
):
    async with db_container() as container:
        session = container.session()
        repo = container.user_repo()
        await session.execute(
            sa.update(Users).where(Users.id == admin_user.id).values(used_tokens=17)
        )
        duplicate = UserAdd(
            email=admin_user.email,
            tenant_id=admin_user.tenant_id,
            state=UserState.ACTIVE,
        )
        with pytest.raises(UniqueException):
            await repo.add(duplicate)
        recovered = await repo.get_user_by_email(admin_user.email)
        assert recovered is not None
        assert recovered.id == admin_user.id
        assert recovered.used_tokens == 17
