"""Global registry of config capabilities.

Capability modules call ``register()`` at import time; importing
``intric.config_capabilities.capabilities`` populates the registry. Both the
loopback config-MCP and the (future) form plane read from here.
"""

from __future__ import annotations

from intric.config_capabilities.capability import ConfigCapability

CAPABILITY_REGISTRY: dict[str, ConfigCapability] = {}


def register(capability: ConfigCapability) -> ConfigCapability:
    if capability.id in CAPABILITY_REGISTRY:
        raise ValueError(f"Duplicate capability id: {capability.id}")
    CAPABILITY_REGISTRY[capability.id] = capability
    return capability


def get_capability(capability_id: str) -> ConfigCapability:
    return CAPABILITY_REGISTRY[capability_id]
