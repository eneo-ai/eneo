from copy import deepcopy
from datetime import datetime
from enum import Enum
from typing import Any, Generic, Optional, Tuple, Type, TypeVar, Union
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

from intric.main.exceptions import ErrorCodes

T = TypeVar("T")


# Sentinel class to distinguish between "not provided" and "explicitly set to None"
class NotProvided:
    """Sentinel value to indicate a parameter was not provided in a request."""

    def __repr__(self):
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
def partial_model(model: Type[BaseModel]):
    def make_field_optional(field: FieldInfo, default: Any = None) -> Tuple[Any, FieldInfo]:
        new = deepcopy(field)
        new.default = default
        new.annotation = Optional[field.annotation]  # type: ignore
        return new.annotation, new

    return create_model(
        f"Partial{model.__name__}",
        __base__=model,
        __module__=model.__module__,
        **{
            field_name: make_field_optional(field_info)
            for field_name, field_info in model.model_fields.items()
        },
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


class CursorPaginatedResponse(PaginatedResponse):
    limit: Optional[int] = None
    next_cursor: Optional[Union[datetime, str]] = None
    previous_cursor: Optional[Union[datetime, str]] = None
    total_count: int


class PaginatedResponseWithPublicItems(PaginatedResponse):
    public_count: int = Field(description="Number of items returned in the response")
    public_items: list[T] = Field(description="List of items returned in the response")


class PaginatedPermissions(PaginatedResponse, ResourcePermissionsMixin):
    pass


class GeneralError(BaseModel):
    message: str
    intric_error_code: ErrorCodes


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
    additional_data: dict | None = None
