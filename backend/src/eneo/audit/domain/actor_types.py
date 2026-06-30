from enum import Enum


class ActorType(str, Enum):
    """Categorize who performed the action"""

    USER = "user"
    SYSTEM = "system"
    API_KEY = "api_key"
