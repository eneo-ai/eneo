"""Single gate for the entire eneo-knowledge integration."""

from intric.main.config import get_settings


def is_enabled() -> bool:
    """Return True when the deployment is configured to talk to eneo-knowledge.

    Two settings are required: the base URL and the API key. The embedding
    model is picked server-side by eneo-knowledge, so eneo does not need
    any extra configuration to start using the integration.
    """
    settings = get_settings()
    return bool(settings.knowledge_url and settings.knowledge_api_key)
