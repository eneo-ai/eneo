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
    API_KEY = "api_key"
    ROLE = "role"
    MODULE = "module"
    TEMPLATE = "template"
    GROUP_CHAT = "group_chat"
    COLLECTION = "collection"
    APP_RUN = "app_run"
    SECURITY_CLASSIFICATION = "security_classification"
    INTEGRATION = "integration"
    INTEGRATION_KNOWLEDGE = "integration_knowledge"
    COMPLETION_MODEL = "completion_model"
    EMBEDDING_MODEL = "embedding_model"
    TRANSCRIPTION_MODEL = "transcription_model"
