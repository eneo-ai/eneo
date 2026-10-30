from __future__ import annotations

from enum import Enum


class PrincipalType(str, Enum):
    USER = "user"
    SERVICE_KEY = "service_key"
