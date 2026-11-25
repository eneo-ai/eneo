from typing import TYPE_CHECKING, Literal, Optional, TypedDict
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from eneo.jobs.job_models import Task
from eneo.object_content.content import StorageKind

if TYPE_CHECKING:
    from eneo.users.user import UserInDB


class TaskActor(TypedDict):
    """Who a job runs as, in the fields ``TaskParams`` carries."""

    user_id: UUID | None
    service_principal_id: UUID | None
    api_key_id: UUID | None
    tenant_id: UUID | None
    acting_space_id: UUID | None


def task_actor(user: "UserInDB") -> TaskActor:
    """The caller as a job's actor.

    A person is named by ``user_id``. A service key has no person behind it:
    the job belongs to the key's service principal, and the key's own id lets
    the worker sign the caller in again with the same rights. A space running
    its own scheduled work is named by ``acting_space_id``.
    """
    acting_space_id = getattr(user, "acting_space_id", None)
    if isinstance(acting_space_id, UUID):
        return {
            "user_id": None,
            "service_principal_id": None,
            "api_key_id": None,
            "tenant_id": user.tenant_id,
            "acting_space_id": acting_space_id,
        }
    key = getattr(user, "active_api_key", None)
    if key is not None and str(getattr(key.ownership, "value", key.ownership)) == (
        "service"
    ):
        if key.service_principal_id is None:
            raise ValueError("A service key without a service principal owns no job")
        return {
            "user_id": None,
            "service_principal_id": key.service_principal_id,
            "api_key_id": key.id,
            "tenant_id": user.tenant_id,
            "acting_space_id": None,
        }
    return {
        "user_id": user.id,
        "service_principal_id": None,
        "api_key_id": None,
        "tenant_id": user.tenant_id,
        "acting_space_id": None,
    }


class TaskParams(BaseModel):
    # Who the job runs as: a person (user_id), or a service key
    # (service_principal_id owns the job, api_key_id signs the caller in again
    # in the worker). tenant_id says where, when there is no person to ask.
    user_id: UUID | None = None
    service_principal_id: UUID | None = None
    api_key_id: UUID | None = None
    tenant_id: UUID | None = None
    # The space whose own scheduled work this is; no person or service then.
    acting_space_id: UUID | None = None

    @model_validator(mode="after")
    def one_actor(self) -> "TaskParams":
        if self.user_id is not None and self.service_principal_id is not None:
            raise ValueError("A job runs as a person or a service, not both")
        if self.acting_space_id is not None and (
            self.user_id is not None
            or self.service_principal_id is not None
            or self.tenant_id is None
        ):
            raise ValueError("A space's own job names its organisation and nobody else")
        if self.service_principal_id is not None and (
            self.api_key_id is None or self.tenant_id is None
        ):
            raise ValueError("A service job names its key and its organisation")
        return self

    def same_actor(
        self, user_id: UUID | None, service_principal_id: UUID | None
    ) -> bool:
        """Whether these params run as exactly this owner."""
        return (
            self.user_id == user_id
            and self.service_principal_id == service_principal_id
        )


class ResourceTaskParams(TaskParams):
    id: UUID


class KnowledgeTask(TaskParams):
    group_id: Optional[UUID] = None
    website_id: Optional[UUID] = None


class InfoBlobTask(TaskParams):
    group_id: UUID
    space_id: UUID


class KnowledgeOriginalAdmission(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_revision: int = Field(ge=1)
    storage_target: StorageKind
    maximum_bytes: int = Field(ge=1)


class UploadTask(InfoBlobTask):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    mimetype: str
    original_storage: KnowledgeOriginalAdmission


class UpdateUsageStatsTaskParams(TaskParams):
    """Parameters for updating completion model usage statistics."""

    @model_validator(mode="after")
    def names_its_organisation(self) -> "UpdateUsageStatsTaskParams":
        if self.tenant_id is None:
            raise ValueError("A usage statistics job names its organisation")
        return self

    model_id: Optional[UUID] = None
    full_recalc: bool = False


class UploadInfoBlob(UploadTask):
    pass


class Transcription(UploadTask):
    pass


class AppDispatchEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    file_ids: list[UUID]


class UploadInfoBlobDispatchEnvelope(BaseModel):
    version: Literal[2] = 2
    task: Literal[Task.UPLOAD_FILE] = Task.UPLOAD_FILE
    params: UploadInfoBlob


class TranscriptionDispatchEnvelope(BaseModel):
    version: Literal[2] = 2
    task: Literal[Task.TRANSCRIPTION] = Task.TRANSCRIPTION
    params: Transcription


DispatchEnvelope = UploadInfoBlobDispatchEnvelope | TranscriptionDispatchEnvelope
_DISPATCH_ENVELOPE_ADAPTER: TypeAdapter[DispatchEnvelope] = TypeAdapter(
    DispatchEnvelope
)


def build_dispatch_envelope(
    task: Task, params: UploadInfoBlob | Transcription
) -> DispatchEnvelope:
    if task == Task.UPLOAD_FILE and isinstance(params, UploadInfoBlob):
        return UploadInfoBlobDispatchEnvelope(params=params)
    if task == Task.TRANSCRIPTION and isinstance(params, Transcription):
        return TranscriptionDispatchEnvelope(params=params)
    raise ValueError(f"Unsupported durable dispatch task: {task.value}")


def validate_dispatch_envelope(value: object) -> DispatchEnvelope:
    return _DISPATCH_ENVELOPE_ADAPTER.validate_python(value)


class AnalyzeConversationInsightsTask(TaskParams):
    # The question lives in the analysis job record. Jobs queued by earlier
    # releases still carry it here; the task ignores this field.
    question: str | None = None
    from_date: str
    to_date: str
    include_followups: bool = False
    assistant_id: UUID | None = None
