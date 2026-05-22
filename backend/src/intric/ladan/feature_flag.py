"""Single gate for the entire Ladan integration."""

from intric.main.config import get_settings


def is_enabled() -> bool:
    """Return True when the deployment is configured to talk to Ladan.

    Two settings are required: the base URL and the API key. The embedding
    model is picked server-side by Ladan, so eneo does not need any extra
    configuration to start using the integration.
    """
    settings = get_settings()
    return bool(settings.ladan_url and settings.ladan_api_key)
