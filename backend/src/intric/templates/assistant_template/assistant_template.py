from typing import TYPE_CHECKING, Optional

from intric.main.exceptions import BadRequestException
from intric.spaces.api.space_models import WizardType


if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from intric.ai_models.completion_models.completion_model import (
        CompletionModelPublic,
    )
    from intric.spaces.api.space_models import TemplateCreate

    from intric.templates.assistant_template.api.assistant_template_models import (
        AssistantTemplateWizard,
    )


class AssistantTemplate:
    def __init__(
        self,
        id: "UUID",
        name: str,
        description: str,
        category: str,
        prompt_text: str,
        created_at: "datetime",
        updated_at: "datetime",
        completion_model: "CompletionModelPublic",
        completion_model_kwargs: dict,
        wizard: "AssistantTemplateWizard",
        organization: str,
        tenant_id: Optional["UUID"] = None,
        deleted_at: Optional["datetime"] = None,
        original_snapshot: Optional[dict] = None,
        deleted_by_user_id: Optional["UUID"] = None,
        restored_by_user_id: Optional["UUID"] = None,
        restored_at: Optional["datetime"] = None,
        is_default: bool = False,
    ):
        self.id = id
        self.name = name
        self.description = description
        self.category = category
        self.prompt_text = prompt_text
        self.completion_model_kwargs = completion_model_kwargs
        self.wizard = wizard
        self.completion_model = completion_model
        self.created_at = created_at
        self.updated_at = updated_at
        self.organization = organization
        # New fields for tenant-scoped template management
        self.tenant_id = tenant_id  # NULL = global/system template, NOT NULL = tenant-specific
        self.deleted_at = deleted_at  # NULL = active, NOT NULL = soft-deleted
        self.original_snapshot = original_snapshot  # Snapshot for rollback functionality
        # Audit trail fields
        self.deleted_by_user_id = deleted_by_user_id
        self.restored_by_user_id = restored_by_user_id
        self.restored_at = restored_at
        # Featured template configuration
        self.is_default = is_default  # True = featured/default template

    def validate_assistant_wizard_data(self, template_data: "TemplateCreate") -> None:
        for data in template_data.additional_fields:
            if data.type == WizardType.attachments:
                if (
                    self.wizard.attachments is None
                    or self.wizard.attachments.required is False
                ):
                    raise BadRequestException(
                        "Unexpected attachments data when creating assistant"
                    )
            elif data.type == WizardType.groups:
                if (
                    self.wizard.collections is None
                    or self.wizard.collections.required is False
                ):
                    raise BadRequestException(
                        "Unexpected groups data when creating assistant"
                    )
            else:
                raise BadRequestException("Unsupported type")

    def is_from_intric(self) -> bool:
        return self.organization == 'default'

    def belongs_to_tenant(self, tenant_id: "UUID") -> bool:
        """Check if template belongs to given tenant (ignoring global templates)."""
        return self.tenant_id == tenant_id

    def is_deleted(self) -> bool:
        """Check if template is soft-deleted."""
        return self.deleted_at is not None

    def is_global(self) -> bool:
        """Check if template is global (available to all tenants)."""
        return self.tenant_id is None

    @classmethod
    def create_snapshot(cls, template_data: dict) -> dict:
        """Create original_snapshot from template data for rollback functionality.

        Args:
            template_data: Dictionary containing template fields

        Returns:
            Dictionary with snapshot of initial state including:
            name, description, category, prompt_text, completion_model_kwargs,
            wizard, completion_model_id, created_at
        """
        snapshot = {
            "name": template_data.get("name"),
            "description": template_data.get("description"),
            "category": template_data.get("category"),
            "prompt_text": template_data.get("prompt_text"),
            "completion_model_kwargs": template_data.get("completion_model_kwargs"),
            "wizard": template_data.get("wizard"),
            "completion_model_id": str(template_data.get("completion_model_id")) if template_data.get("completion_model_id") else None,
        }

        # Add created_at if available (should be datetime object)
        if template_data.get("created_at"):
            created_at = template_data.get("created_at")
            # Convert to ISO format string if datetime object
            if hasattr(created_at, 'isoformat'):
                snapshot["created_at"] = created_at.isoformat()
            else:
                snapshot["created_at"] = created_at

        return snapshot
