"""Pydantic schemas for audit category configuration."""

from pydantic import BaseModel, Field, field_validator

from intric.audit.domain.action_types import ActionType

# Valid category names - must match CATEGORY_DESCRIPTIONS in category_mappings.py
VALID_CATEGORIES = frozenset(
    {
        "admin_actions",
        "user_actions",
        "security_events",
        "file_operations",
        "integration_events",
        "system_actions",
        "audit_access",
    }
)

# Valid action names - derived from ActionType enum
VALID_ACTIONS = frozenset(action.value for action in ActionType)


class CategoryConfig(BaseModel):
    """
    Enriched category configuration with metadata for API responses.
    """

    category: str = Field(..., description="Category name (e.g., 'admin_actions')")
    enabled: bool = Field(..., description="Whether category is currently enabled")
    description: str = Field(..., description="Human-readable description of category")
    action_count: int = Field(
        ..., description="Number of action types in this category"
    )
    example_actions: list[str] = Field(
        ..., description="Sample action types (max 3) for UI display"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "category": "admin_actions",
                "enabled": True,
                "description": "User management, role changes, API keys, tenant settings",
                "action_count": 13,
                "example_actions": [
                    "USER_CREATED",
                    "ROLE_DELETED",
                    "API_KEY_GENERATED",
                ],
            }
        }


class CategoryUpdate(BaseModel):
    """
    Represents a category configuration change request.
    """

    category: str = Field(..., description="Category name to update")
    enabled: bool = Field(..., description="New enabled state")

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        """Validate that category name is one of the allowed values."""
        if v not in VALID_CATEGORIES:
            valid_list = ", ".join(sorted(VALID_CATEGORIES))
            raise ValueError(f"Invalid category '{v}'. Must be one of: {valid_list}")
        return v

    class Config:
        json_schema_extra = {"example": {"category": "admin_actions", "enabled": False}}


class AuditConfigResponse(BaseModel):
    """
    Response model for GET /api/v1/audit/config.
    Contains all 7 categories with metadata.
    """

    categories: list[CategoryConfig] = Field(
        ..., description="List of all audit categories with configuration and metadata"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "categories": [
                    {
                        "category": "admin_actions",
                        "enabled": True,
                        "description": "User management, role changes, API keys, tenant settings",
                        "action_count": 13,
                        "example_actions": [
                            "USER_CREATED",
                            "ROLE_DELETED",
                            "API_KEY_GENERATED",
                        ],
                    },
                    {
                        "category": "user_actions",
                        "enabled": True,
                        "description": "Assistant, space, app operations, templates, model configs",
                        "action_count": 28,
                        "example_actions": [
                            "ASSISTANT_CREATED",
                            "SPACE_DELETED",
                            "APP_EXECUTED",
                        ],
                    },
                ]
            }
        }


class AuditConfigUpdateRequest(BaseModel):
    """
    Request model for PATCH /api/v1/audit/config.
    Allows bulk updates of multiple categories.
    """

    updates: list[CategoryUpdate] = Field(
        ...,
        description="List of category configuration updates",
        min_length=1,
        max_length=7,
    )

    class Config:
        json_schema_extra = {
            "example": {
                "updates": [
                    {"category": "admin_actions", "enabled": False},
                    {"category": "file_operations", "enabled": False},
                ]
            }
        }


class ActionConfig(BaseModel):
    """
    Configuration for a single action type with metadata for UI display.
    """

    action: str = Field(..., description="Action type value (e.g., 'user_created')")
    enabled: bool = Field(..., description="Whether this action is currently enabled")
    category: str = Field(..., description="Category this action belongs to")
    name_sv: str = Field(..., description="Swedish display name")
    description_sv: str = Field(..., description="Swedish description")

    class Config:
        json_schema_extra = {
            "example": {
                "action": "user_created",
                "enabled": True,
                "category": "admin_actions",
                "name_sv": "Användare skapad",
                "description_sv": "Loggar när en ny användare skapas",
            }
        }


class ActionConfigResponse(BaseModel):
    """
    Response model for GET /api/v1/audit/config/actions.
    Contains all 65 actions with their configuration and metadata.
    """

    actions: list[ActionConfig] = Field(
        ..., description="List of all actions with configuration and Swedish metadata"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "actions": [
                    {
                        "action": "user_created",
                        "enabled": True,
                        "category": "admin_actions",
                        "name_sv": "Användare skapad",
                        "description_sv": "Loggar när en ny användare skapas",
                    },
                    {
                        "action": "user_deleted",
                        "enabled": False,
                        "category": "admin_actions",
                        "name_sv": "Användare raderad",
                        "description_sv": "Loggar när en användare tas bort",
                    },
                ]
            }
        }


class ActionUpdate(BaseModel):
    """
    Represents an action-level configuration change request.
    """

    action: str = Field(..., description="Action name to update")
    enabled: bool = Field(..., description="New enabled state")

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        """Validate that action name is one of the allowed ActionType values."""
        if v not in VALID_ACTIONS:
            raise ValueError(
                f"Invalid action '{v}'. Must be a valid ActionType value. "
                f"See ActionType enum for valid values."
            )
        return v

    class Config:
        json_schema_extra = {"example": {"action": "user_created", "enabled": False}}


class ActionConfigUpdateRequest(BaseModel):
    """
    Request model for PATCH /api/v1/audit/config/actions.
    Allows bulk updates of multiple action overrides.
    """

    updates: list[ActionUpdate] = Field(
        ...,
        description="List of action configuration updates",
        min_length=1,
        max_length=65,
    )

    class Config:
        json_schema_extra = {
            "example": {
                "updates": [
                    {"action": "user_created", "enabled": False},
                    {"action": "user_deleted", "enabled": False},
                ]
            }
        }
