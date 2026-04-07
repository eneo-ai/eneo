from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from intric.actors import ActorFactory
    from intric.spaces.space import Space
    from intric.users.user import UserInDB


class ActorManager:
    def __init__(self, user: "UserInDB", factory: "ActorFactory"):
        super().__init__()
        self.user = user
        self.factory = factory

    def get_space_actor_from_space(self, space: "Space"):
        return self.factory.create_space_actor(user=self.user, space=space)
