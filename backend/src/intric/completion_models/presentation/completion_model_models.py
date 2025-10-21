# flake8: noqa

from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel

from intric.ai_models.completion_models.completion_model import (
    CompletionModelPublic,
    CompletionModelUpdateFlags,
)


class ModelUsageStatistics(BaseModel):
    """Pre-aggregated usage statistics for a completion model."""
    model_id: UUID
    total_usage: int
    assistants_count: int
    apps_count: int
    services_count: int
    questions_count: int
    assistant_templates_count: int
    app_templates_count: int
    spaces_count: int
    last_updated: datetime


class ModelUsageDetail(BaseModel):
    """Detailed information about a specific entity using a completion model."""
    entity_id: UUID
    entity_name: str
    entity_type: str  # 'assistant', 'app', 'service', 'assistant_template', 'app_template'
    space_id: Optional[UUID] = None
    space_name: Optional[str] = None
    owner_id: Optional[UUID] = None
    owner_name: Optional[str] = None
    created_at: datetime
    last_used: Optional[datetime] = None
    usage_count: Optional[int] = None  # For questions - number of times used


class ModelMigrationRequest(BaseModel):
    """Request to migrate usage from one model to another."""
    to_model_id: UUID
    entity_types: Optional[List[str]] = None  # If None, migrate all types
    confirm_migration: bool = False


class MigrationResult(BaseModel):
    """Result of a model migration operation."""
    success: bool
    migrated_count: int
    failed_count: int
    details: Dict[str, int]  # Count by entity type
    duration: float  # Duration in seconds
    migration_id: UUID
    warnings: List[str] = []
    auto_recalculated: bool = False  # Whether usage stats were automatically recalculated
    requires_manual_recalculation: bool = False  # Whether manual recalculation is needed


class ValidationResult(BaseModel):
    """Result of migration compatibility validation."""
    compatible: bool
    warnings: List[str]
    requires_confirmation: bool
    user_confirmed: bool = False


class ModelUsageSummary(BaseModel):
    """Summary of usage for a single model."""
    model_id: UUID
    model_name: str
    model_nickname: str
    is_enabled: bool
    total_usage: int
    last_updated: datetime


class MigrationPreview(BaseModel):
    """Preview of what would be migrated."""
    total_count: int
    assistants_count: int
    apps_count: int
    services_count: int
    questions_count: int
    assistant_templates_count: int
    app_templates_count: int
    spaces_count: int


class PaginatedResponse(BaseModel):
    """Generic paginated response with cursor-based pagination."""
    items: List[ModelUsageDetail]
    total: int
    has_more: bool
    next_cursor: Optional[str] = None
    prev_cursor: Optional[str] = None


class ModelMigrationHistory(BaseModel):
    """Historical record of a model migration."""
    id: UUID
    from_model_id: UUID
    from_model_name: str
    to_model_id: UUID
    to_model_name: str
    migrated_count: int
    status: str  # 'pending', 'in_progress', 'completed', 'failed'
    initiated_by_id: UUID
    initiated_by_name: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration: Optional[float] = None  # Duration in seconds
    error_message: Optional[str] = None
