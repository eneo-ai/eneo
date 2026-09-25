import asyncio
from datetime import datetime
from enum import Enum, StrEnum
from typing import Optional, Self
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator

from eneo.files.text import ExtractionError
from eneo.main.exceptions import (
    InfoBlobPublicationConflictError,
    QuotaExceededException,
)
from eneo.main.models import InDB, Status
from eneo.object_content.content import (
    ContentTooLargeError,
    ObjectContentBusyError,
    ObjectContentIntegrityError,
    ObjectContentUnavailableError,
)


class Task(str, Enum):
    UPLOAD_FILE = "upload_info_blob"
    TRANSCRIPTION = "transcription"
    CRAWL = "crawl"
    EMBED_GROUP = "embed_group"
    CRAWL_ALL_WEBSITES = "crawl_all_websites"
    RUN_APP = "run_app"
    PULL_CONFLUENCE_CONTENT = "pull_confluence_content"
    PULL_SHAREPOINT_CONTENT = "pull_sharepoint_content"
    SYNC_SHAREPOINT_DELTA = "sync_sharepoint_delta"
    UPDATE_MODEL_USAGE_STATS = "update_model_usage_stats"
    ANALYZE_CONVERSATION_INSIGHTS = "analyze_conversation_insights"
    EXPORT_AUDIT_LOGS = "export_audit_logs"
    LOG_AUDIT_EVENT = "log_audit_event"


KNOWLEDGE_TASKS = (Task.UPLOAD_FILE, Task.TRANSCRIPTION)


class JobFailureCode(StrEnum):
    EXTRACTION_FAILED = "extraction_failed"
    NO_EXTRACTABLE_TEXT = "no_extractable_text"
    ENCRYPTED = "encrypted"
    CORRUPT = "corrupt"
    UNSUPPORTED_FORMAT = "unsupported_format"
    PROCESSING_FAILED = "processing_failed"
    CANCELLED = "cancelled"
    PROCESSING_INTERRUPTED = "processing_interrupted"
    INVALID_JOB_PAYLOAD = "invalid_job_payload"
    QUOTA_EXCEEDED = "quota_exceeded"
    STORAGE_LIMIT_EXCEEDED = "storage_limit_exceeded"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    STORAGE_VERIFICATION_FAILED = "storage_verification_failed"
    KNOWLEDGE_SOURCE_CONFLICT = "knowledge_source_conflict"


_EXTRACTION_FAILURE_CODES = {
    "EXTRACTION_FAILED": JobFailureCode.EXTRACTION_FAILED,
    "NO_EXTRACTABLE_TEXT": JobFailureCode.NO_EXTRACTABLE_TEXT,
    "ENCRYPTED": JobFailureCode.ENCRYPTED,
    "CORRUPT": JobFailureCode.CORRUPT,
    "UNSUPPORTED_FORMAT": JobFailureCode.UNSUPPORTED_FORMAT,
}


def failure_code_for_exception(error: BaseException) -> JobFailureCode:
    if isinstance(error, asyncio.CancelledError):
        return JobFailureCode.CANCELLED
    if isinstance(error, QuotaExceededException):
        return JobFailureCode.QUOTA_EXCEEDED
    if isinstance(error, ContentTooLargeError):
        return JobFailureCode.STORAGE_LIMIT_EXCEEDED
    if isinstance(error, ObjectContentIntegrityError):
        return JobFailureCode.STORAGE_VERIFICATION_FAILED
    if isinstance(error, (ObjectContentUnavailableError, ObjectContentBusyError)):
        return JobFailureCode.STORAGE_UNAVAILABLE
    if isinstance(error, InfoBlobPublicationConflictError):
        return JobFailureCode.KNOWLEDGE_SOURCE_CONFLICT
    if isinstance(error, ExtractionError):
        return _EXTRACTION_FAILURE_CODES.get(
            error.code,
            JobFailureCode.EXTRACTION_FAILED,
        )
    return JobFailureCode.PROCESSING_FAILED


class JobBase(BaseModel):
    name: Optional[str] = None
    status: Status
    task: Task
    result_location: Optional[str] = None
    finished_at: Optional[datetime] = None


class Job(JobBase):
    user_id: UUID


class JobUpdate(BaseModel):
    status: Optional[Status] = None
    result_location: Optional[str] = None
    failure_code: JobFailureCode | None = None
    finished_at: Optional[datetime] = None


class JobInDb(Job, InDB):
    # Persisted values stay open so an older API replica can read a code written
    # by a newer worker during a rolling deployment. JobPublic closes the API
    # contract and normalizes unknown values to its generic fallback.
    failure_code: str | None = None


class JobPublic(JobBase, InDB):
    failure_code: JobFailureCode | None = None

    @field_validator("failure_code", mode="before")
    @classmethod
    def normalize_failure_code(cls, value: object) -> JobFailureCode | None:
        if value is None:
            return None
        try:
            return JobFailureCode(value)
        except (TypeError, ValueError):
            return None

    @model_validator(mode="after")
    def hide_failed_knowledge_result_location(self) -> Self:
        if self.status == Status.FAILED and self.task in KNOWLEDGE_TASKS:
            self.result_location = None
        return self
