from copy import deepcopy
from datetime import datetime
from enum import Enum
from typing import Any, Generic, Optional, Tuple, Type, TypeVar, Union, cast
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetCoreSchemaHandler,
    computed_field,
    create_model,
)
from pydantic.fields import FieldInfo
from pydantic_core import core_schema
from typing_extensions import TypeIs, override

from eneo.main.exceptions import ErrorCodes

T = TypeVar("T")
_M = TypeVar("_M", bound=BaseModel)


# Sentinel class to distinguish between "not provided" and "explicitly set to None"
class NotProvided:
    """Sentinel value to indicate a parameter was not provided in a request."""

    @override
    def __repr__(self) -> str:
        return "NOT_PROVIDED"

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, _: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.is_instance_schema(
            cls=source_type,
            serialization=core_schema.to_string_ser_schema(),
        )

    def __bool__(self):
        return False


NOT_PROVIDED = NotProvided()


_T_NP = TypeVar("_T_NP")


def is_provided(value: _T_NP | NotProvided) -> TypeIs[_T_NP]:
    """Check if a value was provided (is not the NOT_PROVIDED sentinel).

    Use this instead of ``value is not NOT_PROVIDED`` so that pyright
    can narrow ``T | NotProvided`` to ``T`` in the true branch.
    """
    return not isinstance(value, NotProvided)


class MCPToolSetting(BaseModel):
    """MCP server tool enablement setting."""

    tool_id: UUID
    is_enabled: bool


class ResourcePermission(Enum):
    READ = "read"
    CREATE = "create"
    EDIT = "edit"
    DELETE = "delete"
    ADD = "add"
    REMOVE = "remove"
    PUBLISH = "publish"
    INSIGHT_VIEW = "insight_view"
    INSIGHT_TOGGLE = "insight_toggle"


# Taken from https://stackoverflow.com/questions/67699451/make-every-field-as-optional-with-pydantic
def partial_model(model: Type[_M]) -> Type[_M]:
    def make_field_optional(
        field: FieldInfo, default: Any = None
    ) -> Tuple[Any, FieldInfo]:
        new = deepcopy(field)
        new.default = default
        new.default_factory = (
            None  # Clear default_factory to avoid conflict with default
        )
        new.annotation = Optional[field.annotation]  # type: ignore
        return new.annotation, new

    return cast(
        Type[_M],
        cast(Any, create_model)(
            f"Partial{model.__name__}",
            __base__=model,
            __module__=model.__module__,
            **{
                field_name: make_field_optional(field_info)
                for field_name, field_info in model.model_fields.items()
            },
        ),
    )


class ModelId(BaseModel):
    id: UUID


class DateTimeModelMixin(BaseModel):
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class BaseResponse(ModelId, DateTimeModelMixin):
    pass


class InDB(BaseResponse):
    model_config = ConfigDict(from_attributes=True)


class ResourcePermissionsMixin(BaseModel):
    permissions: list[ResourcePermission] = []


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T] = Field(description="List of items returned in the response")

    @computed_field(description="Number of items returned in the response")
    @property
    def count(self) -> int:
        return len(self.items)


class OffsetPaginatedResponse(PaginatedResponse[T], Generic[T]):
    has_more: bool = Field(
        description="Whether another page exists after the returned offset window"
    )


class CursorPaginatedResponse(PaginatedResponse[T], Generic[T]):
    limit: Optional[int] = None
    next_cursor: Optional[Union[datetime, str]] = None
    previous_cursor: Optional[Union[datetime, str]] = None
    total_count: int


class PaginatedResponseWithPublicItems(PaginatedResponse[T], Generic[T]):
    public_count: int = Field(description="Number of items returned in the response")
    public_items: list[T] = Field(description="List of items returned in the response")


class PaginatedPermissions(PaginatedResponse[T], ResourcePermissionsMixin, Generic[T]):
    pass


class GeneralError(BaseModel):
    message: str = Field(
        description=(
            "Human-readable error message suitable for showing in logs or support "
            "tools. Clients should branch on `code`, not this text."
        )
    )
    eneo_error_code: ErrorCodes = Field(
        description=(
            "Stable numeric Eneo error category retained for existing clients. "
            "Prefer the string `code` field for new control flow."
        )
    )
    code: str = Field(
        min_length=1,
        description=(
            "Machine-readable error code for client and LLM tool control flow. "
            "Examples on each endpoint list representative values."
        ),
    )
    context: dict[str, object] | None = Field(
        default=None,
        description=(
            "Small structured context that explains why the request failed, such as "
            "the authorization layer or conflicting field. Values are safe for API "
            "consumers to log."
        ),
    )
    request_id: str | None = Field(
        default=None,
        description=(
            "Correlation id for support and server logs. Echoes `x-correlation-id` "
            "or `x-request-id` when supplied."
        ),
    )
    error_id: str | None = Field(
        default=None,
        description=(
            "Short support identifier for an unexpected server error. Quote this value "
            "when asking support to locate the originating exception log."
        ),
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional structured diagnostics for errors that need extra machine-readable "
            "data, such as token limits or validation details."
        ),
    )


class DeleteResponse(BaseModel):
    success: bool


class SuccessResponse(DeleteResponse):
    pass


class IdAndName(BaseModel):
    id: UUID
    name: str

    model_config = ConfigDict(from_attributes=True)


class PublicReference(InDB):
    name: str


class ChannelType(str, Enum):
    APP_RUN_UPDATES = "app_run_updates"
    CRAWL_RUN_UPDATES = "crawl_run_updates"
    PULL_CONFLUENCE_CONTENT = "pull_confluence_content"
    PULL_SHAREPOINT_CONTENT = "pull_sharepoint_content"
    SYNC_SHAREPOINT_DELTA = "sync_sharepoint_delta"


class Status(str, Enum):
    IN_PROGRESS = "in progress"
    QUEUED = "queued"
    COMPLETE = "complete"
    FAILED = "failed"
    NOT_FOUND = "not found"


class Channel(BaseModel):
    type: ChannelType
    user_id: UUID

    @computed_field
    @property
    def channel_string(self) -> str:
        return f"{self.type}:{self.user_id}"


class RedisMessage(BaseModel):
    id: UUID
    status: Status
    additional_data: dict[str, object] | None = None
