from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from eneo.files.file_models import FilePublic
from eneo.jobs.task_models import ResourceTaskParams
from eneo.main.models import InDB, ModelId, Status
from eneo.users.user import UserSparse


class RunAppRequest(BaseModel):
    files: list[ModelId] = []
    text: str | None = None


class AppRunInput(BaseModel):
    files: list[FilePublic]
    text: str | None


class AppRunSparse(InDB):
    input: AppRunInput
    status: Status
    finished_at: datetime | None
    user: UserSparse


class AppRunPublic(AppRunSparse):
    output: str | None


class AppRunParams(ResourceTaskParams):
    app_id: UUID
    file_ids: list[UUID]
    text: str | None
