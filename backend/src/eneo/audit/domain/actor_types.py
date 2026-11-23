from enum import Enum


class ActorType(str, Enum):
    """Categorize who performed the action"""

    USER = "user"
    SYSTEM = "system"
    API_KEY = "api_key"
    # An anonymous widget visitor: pseudonymous, never a users row, so the
    # entry carries no actor_id and names the visitor in its metadata instead.
    WIDGET_VISITOR = "widget_visitor"

    @property
    def requires_actor_id(self) -> bool:
        """Whether an entry of this type must name a users row as its actor.

        System entries have no actor, a widget visitor has no row to name,
        and a service key is named through actor_api_key_id instead; every
        other entry is traced to the account that acted.
        """
        return self not in (
            ActorType.SYSTEM,
            ActorType.WIDGET_VISITOR,
            ActorType.API_KEY,
        )
