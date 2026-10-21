"""What a queued integration sync job carries to the worker."""

from typing import Optional
from uuid import UUID

from eneo.jobs.task_models import ResourceTaskParams


class ConfluenceContentTaskParam(ResourceTaskParams):
    token_id: UUID
    space_key: str
    integration_knowledge_id: UUID


class SharepointContentTaskParam(ResourceTaskParams):
    token_id: Optional[UUID] = None  # For user_oauth integrations
    tenant_app_id: Optional[UUID] = None  # For tenant_app integrations
    integration_knowledge_id: UUID
    site_id: Optional[str] = None  # Required for SharePoint, None for OneDrive
    drive_id: Optional[str] = None  # Required for OneDrive, optional for SharePoint
    folder_id: Optional[str] = None
    folder_path: Optional[str] = None
    resource_type: str = "site"  # "site" for SharePoint, "onedrive" for OneDrive
