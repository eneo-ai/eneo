from __future__ import annotations

from enum import Enum


class PrincipalType(str, Enum):
    USER = "user"
    SERVICE_KEY = "service_key"
    # A space acting for itself, for scheduled work nobody stands behind.
    SPACE = "space"
