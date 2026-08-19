"""Flow compatibility name for the shared resource-package byte limit."""

from eneo.resource_packages.limits import MAX_RESOURCE_PACKAGE_BYTES

MAX_FLOW_PACKAGE_BYTES = MAX_RESOURCE_PACKAGE_BYTES

__all__ = ["MAX_FLOW_PACKAGE_BYTES"]
