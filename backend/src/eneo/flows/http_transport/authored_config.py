from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from typing_extensions import TypedDict, TypeGuard

SecretSentinel = TypedDict("SecretSentinel", {"$secret": Literal["stored"]})
SecretValue: TypeAlias = str | SecretSentinel
HttpMethod: TypeAlias = Literal["GET", "POST"]
HttpResponseFormat: TypeAlias = Literal["text", "json"]
SECRET_SENTINEL: SecretSentinel = {"$secret": "stored"}


def is_secret_sentinel(value: object) -> TypeGuard[SecretSentinel]:
    if not isinstance(value, dict):
        return False
    candidate = cast(dict[str, object], value)
    return candidate.get("$secret") == "stored"


def contains_secret_sentinel(value: object) -> bool:
    if is_secret_sentinel(value):
        return True
    if isinstance(value, dict):
        nested_values = cast(dict[object, object], value).values()
        return any(contains_secret_sentinel(nested) for nested in nested_values)
    if isinstance(value, list):
        nested_items = cast(list[object], value)
        return any(contains_secret_sentinel(nested) for nested in nested_items)
    return False


class HttpAuthMode(str, Enum):
    NONE = "none"
    BEARER_TOKEN = "bearer_token"
    API_KEY = "api_key"
    BASIC_AUTH = "basic_auth"


class HttpAuthNone(BaseModel):
    mode: Literal["none"] = "none"


class HttpAuthBearer(BaseModel):
    mode: Literal["bearer_token"] = "bearer_token"
    token: SecretValue = ""


class HttpAuthApiKey(BaseModel):
    mode: Literal["api_key"] = "api_key"
    header_name: str = "X-API-Key"
    key: SecretValue = ""


class HttpAuthBasicAuth(BaseModel):
    mode: Literal["basic_auth"] = "basic_auth"
    username: str = ""
    password: SecretValue = ""


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
    value: SecretValue = ""
    secret: StrictBool = False


def _default_custom_headers() -> list[CustomHeader]:
    return []


class HttpAuthoredConfig(BaseModel):
    """Authored HTTP config — what the user configured.

    Stored in ``input_config`` / ``output_config`` JSONB columns.
    The ``auth`` field is required by the Flow authored HTTP contract gate.
    """

    model_config = ConfigDict(extra="forbid")

    url: str = ""
    auth: HttpAuth = Field(default_factory=HttpAuthNone)
    timeout_seconds: StrictInt = 30
    body: HttpBody = Field(default_factory=lambda: HttpBody(mode=HttpBodyMode.AUTO))
    custom_headers: list[CustomHeader] = Field(default_factory=_default_custom_headers)
    response_format: HttpResponseFormat | None = None
