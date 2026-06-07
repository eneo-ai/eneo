"""Declarative config-capability registry shared by the chat and form planes."""

# Import the capability modules so they self-register on package import.
from intric.config_capabilities import (  # noqa: F401  # side-effect: registers caps
    capabilities as capabilities,
)
from intric.config_capabilities.capability import (
    CapabilityContext,
    CapabilityResult,
    ConfigCapability,
    Scope,
)
from intric.config_capabilities.context import capability_context, run_capability
from intric.config_capabilities.registry import (
    CAPABILITY_REGISTRY,
    get_capability,
    register,
)

__all__ = [
    "CAPABILITY_REGISTRY",
    "CapabilityContext",
    "CapabilityResult",
    "ConfigCapability",
    "Scope",
    "capability_context",
    "get_capability",
    "register",
    "run_capability",
]
