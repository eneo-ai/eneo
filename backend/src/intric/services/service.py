from typing import Annotated, Any, Literal, Optional
from uuid import UUID

from pydantic import (
    AliasChoices,
    AliasPath,
    BaseModel,
    ConfigDict,
    Field,
    SkipValidation,
    model_validator,
)

from intric.ai_models.completion_models.completion_model import (
    CompletionModelPublic,
    ModelKwargs,
)
from intric.completion_models.domain.completion_model import CompletionModel
from intric.files.file_models import FilePublic
from intric.groups_legacy.api.group_models import GroupInDBBase, GroupPublicBase
from intric.info_blobs.info_blob import (
    InfoBlobChunkInDBWithScore,
    InfoBlobInDBWithScore,
    InfoBlobPublic,
)
from intric.main.config import get_settings
from intric.main.models import InDB, ModelId, ResourcePermissionsMixin, partial_model
from intric.users.user import UserInDBBase, UserPublicBase


class OutputValidation(BaseModel):
    output_format: Optional[Literal["json", "list", "boolean"]] = None
    json_schema: Optional[dict] = None

    @model_validator(mode="after")
    def require_json_schema_if_output_format_is_json(self):
        if self.output_format == "json" and self.json_schema is None:
            raise ValueError("json_schema is requred if output_format is 'json'")

        return self


class ServiceBase(OutputValidation):
    name: str
    prompt: str
    completion_model_kwargs: ModelKwargs = Field(default_factory=ModelKwargs)


class ServiceCreatePublic(ServiceBase):
    groups: list[ModelId] = []
    completion_model: ModelId


@partial_model
class ServiceUpdatePublic(ServiceCreatePublic):
    pass


class ServiceCreate(ServiceBase):
    user_id: UUID
    groups: list[ModelId] = []
    completion_model_id: UUID = Field(
        validation_alias=AliasChoices(AliasPath("completion_model", "id"), "completion_model_id")
    )


@partial_model
class ServiceUpdate(ServiceCreate):
    id: UUID


class ServiceInDBBase(InDB, ServiceBase):
    tenant_id: UUID = Field(validation_alias=AliasPath(["user", "tenant_id"]))


class Service(InDB, ServiceBase, ResourcePermissionsMixin):
    user_id: UUID
    space_id: Optional[UUID] = None
    groups: list[GroupInDBBase]
    completion_model_id: UUID
    completion_model: Annotated[Optional[CompletionModel], SkipValidation] = None
    user: UserInDBBase

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ServicePublicBase(InDB, OutputValidation):
    name: str
    prompt: str
    completion_model_kwargs: Optional[ModelKwargs] = None
    space_id: Optional[UUID] = None


class ServicePublic(ServicePublicBase, ResourcePermissionsMixin):
    groups: list[GroupPublicBase]
    completion_model: CompletionModelPublic


class ServicePublicWithUser(ServicePublic):
    user: UserPublicBase


class RunService(BaseModel):
    input: str
    files: list[ModelId] = Field(max_length=get_settings().max_in_question, default=[])


class ServiceOutput(BaseModel):
    output: Any
    files: list[FilePublic] = []


class ServiceRun(BaseModel):
    id: UUID
    input: str
    output: dict | list | str
    completion_model: CompletionModelPublic
    references: list[InfoBlobPublic]


class DatastoreResult(BaseModel):
    chunks: list[InfoBlobChunkInDBWithScore]
    no_duplicate_chunks: list[InfoBlobChunkInDBWithScore]
    info_blobs: list[InfoBlobInDBWithScore]


class RunnerResult(BaseModel):
    result: bool | list | dict | str
    datastore_result: DatastoreResult
    files: list[FilePublic] = []


class ServiceSparse(ResourcePermissionsMixin, ServiceBase, InDB):
    user_id: UUID


class CreateSpaceService(ServiceCreate):
    space_id: UUID
    completion_model_id: Optional[UUID] = None
