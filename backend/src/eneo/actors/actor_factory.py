from typing import TYPE_CHECKING

from eneo.actors.actors.space_actor import SpaceAccessFacts, SpaceActor

if TYPE_CHECKING:
    from eneo.users.user import UserInDB


class ActorFactory:
    @staticmethod
    def create_space_actor(user: "UserInDB", space: SpaceAccessFacts):
        return SpaceActor(user=user, space=space)
