"""Importing this package registers all config capabilities in the registry."""

from intric.config_capabilities.capabilities import (
    assistant_grants,
    assistant_settings,
    collections,
    websites,
)

# Re-export so the side-effect imports (which trigger register()) count as used.
__all__ = ["assistant_grants", "assistant_settings", "collections", "websites"]
