from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, computed_field


class TemplateWizard(BaseModel):
    required: bool = False
    title: Optional[str] = None
    description: Optional[str] = None


class AssistantTemplateWizard(BaseModel):
    attachments: Optional[TemplateWizard]
    collections: Optional[TemplateWizard]


class CompletionModelPublicAssistantTemplate(BaseModel):
    id: UUID


class PromptPublicAssistantTemplate(BaseModel):
    text: Optional[str]


class AssistantTemplateOrganization(BaseModel):
    name: str


class AssistantInTemplatePublic(BaseModel):
    name: str
    completion_model: Optional[CompletionModelPublicAssistantTemplate]
    completion_model_kwargs: dict = Field(default={})
    prompt: Optional[PromptPublicAssistantTemplate]


class AssistantTemplatePublic(BaseModel):
    id: UUID
    created_at: datetime
    updated_at: datetime
    name: str
    description: str
    category: str
    assistant: AssistantInTemplatePublic
    type: Literal["assistant"]
    wizard: AssistantTemplateWizard
    organization: AssistantTemplateOrganization
    is_default: bool = False


class AssistantTemplateListPublic(BaseModel):
    items: list[AssistantTemplatePublic]

    @computed_field(description="Number of items returned in the response")
    @property
    def count(self) -> int:
        return len(self.items)


class AssistantTemplateCreate(BaseModel):
    name: str
    description: str
    category: str
    prompt: str
    organization: Optional[str] = None
    completion_model_kwargs: Optional[dict] = {}
    wizard: AssistantTemplateWizard


class AssistantTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    prompt: Optional[str] = None
    organization: Optional[str] = None
    completion_model_kwargs: Optional[dict] = None
    wizard: Optional[AssistantTemplateWizard] = None


# Admin-specific models for tenant-scoped templates

class AssistantTemplateAdminPublic(BaseModel):
    """Admin view of template with tenant fields."""
    id: UUID
    name: str
    description: str
    category: str
    prompt_text: Optional[str] = None
    completion_model_kwargs: Optional[dict] = Field(default={})
    wizard: Optional[AssistantTemplateWizard] = None
    organization: str
    tenant_id: UUID
    deleted_at: Optional[datetime] = None
    deleted_by_user_id: Optional[UUID] = None
    restored_at: Optional[datetime] = None
    restored_by_user_id: Optional[UUID] = None
    original_snapshot: Optional[dict] = None
    created_at: datetime
    updated_at: datetime
    usage_count: int = 0  # Number of assistants created from this template
    is_default: bool = False


class AssistantTemplateAdminListPublic(BaseModel):
    """Admin list response."""
    items: list[AssistantTemplateAdminPublic]

    @computed_field
    @property
    def count(self) -> int:
        return len(self.items)


class AssistantTemplateAdminCreate(BaseModel):
    """Admin template creation request."""
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1, max_length=2000)
    category: str = Field(..., min_length=1, max_length=100)
    prompt: Optional[str] = None
    completion_model_kwargs: Optional[dict] = Field(default={})
    wizard: Optional[AssistantTemplateWizard] = None


class AssistantTemplateAdminUpdate(BaseModel):
    """Admin template update request (PATCH semantics)."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, min_length=1, max_length=2000)
    category: Optional[str] = Field(None, min_length=1, max_length=100)
    prompt: Optional[str] = None
    completion_model_kwargs: Optional[dict] = None
    wizard: Optional[AssistantTemplateWizard] = None


class AssistantTemplateToggleDefaultRequest(BaseModel):
    """Request to toggle template as default/featured."""
    is_default: bool
