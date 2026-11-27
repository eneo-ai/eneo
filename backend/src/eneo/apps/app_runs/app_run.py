from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from eneo.files.file_models import FileInfo
from eneo.jobs.job_models import JobInDb
from eneo.skills.domain.skill import SkillExecutionReference
from eneo.users.user import UserSparse


@dataclass
class AppRun:
    created_at: datetime | None
    updated_at: datetime | None
    id: UUID | None
    job_id: UUID | None
    app_id: UUID
    # The owner: the person who started the run, or (below) the service
    # principal of the service key that did.
    user_id: UUID | None
    tenant_id: UUID
    input_files: list[FileInfo]
    input_text: str | None
    output: str | None
    user: UserSparse | None
    num_tokens_input: int | None
    num_tokens_output: int | None
    # Pinned prompt-composition lineage remains truthful if execution fails early.
    skill_provenance: tuple[SkillExecutionReference, ...] | None
    job: JobInDb | None
    completion_model_id: UUID
    service_principal_id: UUID | None = None

    def owned_by(self, user_id: UUID | None, service_principal_id: UUID | None) -> bool:
        """Whether the run belongs to exactly this owner; a run with no owner
        belongs to nobody."""
        if self.user_id is not None:
            return self.user_id == user_id
        if self.service_principal_id is not None:
            return self.service_principal_id == service_principal_id
        return False

    def update(
        self,
        *,
        job_id: UUID | None = None,
        output: str | None = None,
        num_tokens_input: int | None = None,
        num_tokens_output: int | None = None,
        skill_provenance: tuple[SkillExecutionReference, ...] | None = None,
    ):
        if job_id is not None:
            self.job_id = job_id

        if output is not None:
            self.output = output

        if num_tokens_input is not None:
            self.num_tokens_input = num_tokens_input

        if num_tokens_output is not None:
            self.num_tokens_output = num_tokens_output

        if skill_provenance is not None:
            self.skill_provenance = skill_provenance
