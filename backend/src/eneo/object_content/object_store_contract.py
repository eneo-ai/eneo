"""Shared object-store outcomes and opaque key creation.

The content lifecycle uses these without initializing the remote S3 adapter.
"""

from enum import StrEnum
from secrets import token_hex

from eneo.object_content.configuration import ObjectContentSettings


class ObjectStoreError(RuntimeError):
    """Base exception for the private object-content boundary."""


class ObjectStoreUnavailableError(ObjectStoreError):
    pass


class ObjectStoreNotFoundError(ObjectStoreError):
    pass


class ObjectStoreIntegrityError(ObjectStoreError):
    pass


class ObjectStoreBindingError(ObjectStoreError):
    pass


class ObjectStoreProbeCleanupError(ObjectStoreError):
    pass


class ObjectStoreFailureKind(StrEnum):
    AUTHENTICATION = "authentication"
    TLS = "tls"
    CONNECTION = "connection"
    UNAVAILABLE = "unavailable"


def new_object_key(settings: ObjectContentSettings) -> str:
    """Create an opaque key with only a deployment namespace and random token."""
    return f"{settings.object_key_prefix}{token_hex(16)}"
