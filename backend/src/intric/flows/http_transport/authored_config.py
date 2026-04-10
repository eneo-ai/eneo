from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class HttpAuthMode(str, Enum):
    NONE = "none"
    BEARER_TOKEN = "bearer_token"
    API_KEY = "api_key"
    BASIC_AUTH = "basic_auth"


class HttpAuthNone(BaseModel):
    mode: Literal["none"] = "none"


class HttpAuthBearer(BaseModel):
    mode: Literal["bearer_token"] = "bearer_token"
    token: str = ""


class HttpAuthApiKey(BaseModel):
    mode: Literal["api_key"] = "api_key"
    header_name: str = "X-API-Key"
    key: str = ""


class HttpAuthBasicAuth(BaseModel):
    mode: Literal["basic_auth"] = "basic_auth"
    username: str = ""
    password: str = ""


HttpAuth = Annotated[
    HttpAuthNone | HttpAuthBearer | HttpAuthApiKey | HttpAuthBasicAuth,
    Field(discriminator="mode"),
]


class HttpBodyMode(str, Enum):
    AUTO = "auto"
    JSON_TEMPLATE = "json_template"
    TEXT_TEMPLATE = "text_template"
    NONE = "none"


class HttpBody(BaseModel):
    mode: HttpBodyMode = HttpBodyMode.AUTO
    template: str | None = None


class CustomHeader(BaseModel):
    name: str = ""
    value: str | dict[str, Any] = ""
    secret: bool = False


def _default_custom_headers() -> list[CustomHeader]:
    return []


class HttpAuthoredConfig(BaseModel):
    """Authored HTTP config — what the user configured.

    Stored in ``input_config`` / ``output_config`` JSONB columns.
    The ``auth`` field distinguishes this from legacy dict configs.
    """

    url: str = ""
    auth: HttpAuth = Field(default_factory=HttpAuthNone)
    timeout_seconds: int = 30
    body: HttpBody = Field(default_factory=lambda: HttpBody(mode=HttpBodyMode.AUTO))
    custom_headers: list[CustomHeader] = Field(default_factory=_default_custom_headers)
    response_format: str | None = None
