from eneo.main.container.container import Container
from eneo.users.user import UserInDB, UserUpdate


async def setup_user(container: Container, user: UserInDB):
    user_repo = container.user_repo()

    user_update = UserUpdate(is_active=True, id=user.id)
    await user_repo.update(user=user_update)
