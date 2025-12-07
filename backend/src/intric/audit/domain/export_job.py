"""Export job domain model for tracking async audit log exports."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ExportJobStatus(str, Enum):
    """Status of an export job."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExportJob(BaseModel):
    """Represents an async audit log export job.

    This model is stored in Redis for job tracking and progress monitoring.
    Files are stored on disk at /app/exports/{tenant_id}/{job_id}.{format}

    Attributes:
        job_id: Unique identifier for the export job
        tenant_id: Tenant ID for multi-tenant isolation
        status: Current job status
        progress: Progress percentage (0-100)
        total_records: Total number of records to export (0 if unknown)
        processed_records: Number of records processed so far
        format: Export format (csv or jsonl)
        file_path: Path to generated file (set when completed)
        file_size_bytes: Size of generated file in bytes
        error_message: Error details if status is FAILED
        cancelled: Flag to signal worker to stop processing
        created_at: When the job was created
        started_at: When processing started
        completed_at: When processing finished (success, failure, or cancel)
        expires_at: When the job and file should be cleaned up
    """

    job_id: UUID
    tenant_id: UUID
    status: ExportJobStatus = ExportJobStatus.PENDING
    progress: int = Field(default=0, ge=0, le=100)
    total_records: int = Field(default=0, ge=0)
    processed_records: int = Field(default=0, ge=0)
    format: str = "csv"
    file_path: Optional[str] = None
    file_size_bytes: Optional[int] = None
    error_message: Optional[str] = None
    cancelled: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )  # Updated by manager

    def to_redis_dict(self) -> dict:
        """Convert to dict for Redis storage."""
        return {
            "job_id": str(self.job_id),
            "tenant_id": str(self.tenant_id),
            "status": self.status.value,
            "progress": self.progress,
            "total_records": self.total_records,
            "processed_records": self.processed_records,
            "format": self.format,
            "file_path": self.file_path,
            "file_size_bytes": self.file_size_bytes,
            "error_message": self.error_message,
            "cancelled": self.cancelled,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "expires_at": self.expires_at.isoformat(),
        }

    @classmethod
    def from_redis_dict(cls, data: dict) -> "ExportJob":
        """Create from Redis-stored dict."""
        return cls(
            job_id=UUID(data["job_id"]),
            tenant_id=UUID(data["tenant_id"]),
            status=ExportJobStatus(data["status"]),
            progress=data["progress"],
            total_records=data["total_records"],
            processed_records=data["processed_records"],
            format=data["format"],
            file_path=data.get("file_path"),
            file_size_bytes=data.get("file_size_bytes"),
            error_message=data.get("error_message"),
            cancelled=data.get("cancelled", False),
            created_at=datetime.fromisoformat(data["created_at"]),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            expires_at=datetime.fromisoformat(data["expires_at"]),
        )

    def is_terminal(self) -> bool:
        """Check if job is in a terminal state (no more updates expected)."""
        return self.status in (
            ExportJobStatus.COMPLETED,
            ExportJobStatus.FAILED,
            ExportJobStatus.CANCELLED,
        )

    def can_be_cancelled(self) -> bool:
        """Check if job can be cancelled."""
        return self.status in (ExportJobStatus.PENDING, ExportJobStatus.PROCESSING)
