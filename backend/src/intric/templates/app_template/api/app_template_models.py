from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

from intric.apps.apps.api.app_models import InputFieldType


class TemplateWizard(BaseModel):
    required: bool = False
    title: Optional[str] = None
    description: Optional[str] = None


class AppTemplateWizard(BaseModel):
    attachments: Optional[TemplateWizard]
    collections: Optional[TemplateWizard]

    @model_validator(mode="after")
    def validate_collections(self):
        # No collections are allowed for App
        if self.collections is not None:
            raise ValueError("The 'collections' field must always be None.")
        return self


class CompletionModelPublicAppTemplate(BaseModel):
    id: UUID


class PromptPublicAppTemplate(BaseModel):
    text: Optional[str]


class AppTemplateOrganization(BaseModel):
    name: str


class AppInTemplatePublic(BaseModel):
    name: str
    completion_model: Optional[CompletionModelPublicAppTemplate]
    completion_model_kwargs: dict
    prompt: Optional[PromptPublicAppTemplate]
    input_description: Optional[str]
    input_type: str


class AppTemplatePublic(BaseModel):
    id: UUID
    created_at: datetime
    updated_at: datetime
    name: str
    description: Optional[str]
    category: str
    app: AppInTemplatePublic
    type: Literal["app"]
    wizard: AppTemplateWizard
    organization: AppTemplateOrganization
    is_default: bool = False
    icon_name: Optional[str] = None


class AppTemplateListPublic(BaseModel):
    items: list[AppTemplatePublic]

    @computed_field(description="Number of items returned in the response")
    @property
    def count(self) -> int:
        return len(self.items)


class AppTemplateCreate(BaseModel):
    name: str
    description: str
    category: str
    prompt: str
    organization: Optional[str] = None
    completion_model_kwargs: dict = Field(default_factory=dict)
    wizard: AppTemplateWizard
    input_type: str
    input_description: Optional[str]
    icon_name: Optional[str] = None

    @model_validator(mode="after")
    def validate_input_type(self):
        if not InputFieldType.contains_input_type(self.input_type):
            raise ValueError("Not a valid input type for App")
        return self


class AppTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    prompt: Optional[str] = None
    organization: Optional[str] = None
    completion_model_kwargs: Optional[dict] = None
    completion_model_id: Optional[UUID] = None
    wizard: Optional[AppTemplateWizard] = None
    input_type: Optional[str] = None
    input_description: Optional[str] = None
    icon_name: Optional[str] = None


# Admin-specific models for tenant-scoped templates

class AppTemplateAdminPublic(BaseModel):
    """Admin view of template with tenant fields."""
    id: UUID
    name: str
    description: str
    category: str
    prompt_text: Optional[str] = None
    completion_model_kwargs: dict = Field(default_factory=dict)
    completion_model_id: Optional[UUID] = None
    completion_model_name: Optional[str] = None
    wizard: Optional[AppTemplateWizard] = None
    input_type: str
    input_description: Optional[str] = None
    organization: str
    tenant_id: UUID
    deleted_at: Optional[datetime] = None
    deleted_by_user_id: Optional[UUID] = None
    restored_at: Optional[datetime] = None
    restored_by_user_id: Optional[UUID] = None
    original_snapshot: Optional[dict] = None
    created_at: datetime
    updated_at: datetime
    usage_count: int = 0  # Number of apps created from this template
    is_default: bool = False
    icon_name: Optional[str] = None


class AppTemplateAdminListPublic(BaseModel):
    """Admin list response."""
    items: list[AppTemplateAdminPublic]

    @computed_field
    @property
    def count(self) -> int:
        return len(self.items)


class AppTemplateAdminCreate(BaseModel):
    """Admin template creation request."""
    name: str
    description: Optional[str] = None
    category: str
    prompt: Optional[str] = None
    completion_model_kwargs: dict = Field(default_factory=dict)
    wizard: Optional[AppTemplateWizard] = None
    input_type: str
    input_description: Optional[str] = None
    icon_name: Optional[str] = None


class AppTemplateAdminUpdate(BaseModel):
    """Admin template update request (PATCH semantics)."""
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    prompt: Optional[str] = None
    completion_model_kwargs: Optional[dict] = None
    completion_model_id: Optional[UUID] = None
    wizard: Optional[AppTemplateWizard] = None
    input_type: Optional[str] = None
    input_description: Optional[str] = None
    icon_name: Optional[str] = None

    @field_validator("name", "description", "category", "icon_name", mode="before")
    @classmethod
    def empty_str_to_none(cls, v):
        """Convert empty strings to None to allow clearing optional fields."""
        if isinstance(v, str) and v.strip() == "":
            return None
        return v


class AppTemplateToggleDefaultRequest(BaseModel):
    """Request to toggle template as default/featured."""
    is_default: bool
