from enum import Enum


class EntityType(str, Enum):
    """Categorize what type of entity was affected"""

    USER = "user"
    ASSISTANT = "assistant"
    SPACE = "space"
    APP = "app"
    FILE = "file"
    WEBSITE = "website"
    TENANT_SETTINGS = "tenant_settings"
    CREDENTIAL = "credential"
    FEDERATION_CONFIG = "federation_config"
