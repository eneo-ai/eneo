"""Pydantic schemas for audit category configuration."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.category_types import CategoryType

# Valid category names - derived from CategoryType enum
VALID_CATEGORIES = frozenset(category.value for category in CategoryType)

# Valid action names - derived from ActionType enum
VALID_ACTIONS = frozenset(action.value for action in ActionType)


class CategoryConfig(BaseModel):
    """
    Category configuration for API responses.

    Display text is intentionally omitted: the frontend translates ``category``
    by key (``audit_category_{category}`` / ``_description``).
    """

    category: CategoryType = Field(
        ..., description="Category key (e.g., 'admin_actions')"
    )
    enabled: bool = Field(..., description="Whether category is currently enabled")
    action_count: int = Field(
        ..., description="Number of action types in this category"
    )
    example_actions: list[str] = Field(
        ..., description="Sample action types (max 3) for UI display"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "category": "admin_actions",
                "enabled": True,
                "action_count": 13,
                "example_actions": [
                    "user_created",
                    "role_deleted",
                    "api_key_generated",
                ],
            }
        }
    )


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

    model_config = ConfigDict(
        json_schema_extra={"example": {"category": "admin_actions", "enabled": False}}
    )


class AuditConfigResponse(BaseModel):
    """
    Response model for GET /api/v1/audit/config.
    Contains all 7 categories with metadata.
    """

    categories: list[CategoryConfig] = Field(
        ..., description="List of all audit categories with configuration and metadata"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "categories": [
                    {
                        "category": "admin_actions",
                        "enabled": True,
                        "action_count": 13,
                        "example_actions": [
                            "user_created",
                            "role_deleted",
                            "api_key_generated",
                        ],
                    },
                    {
                        "category": "user_actions",
                        "enabled": True,
                        "action_count": 28,
                        "example_actions": [
                            "assistant_created",
                            "space_deleted",
                            "app_executed",
                        ],
                    },
                ]
            }
        }
    )


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

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "updates": [
                    {"category": "admin_actions", "enabled": False},
                    {"category": "file_operations", "enabled": False},
                ]
            }
        }
    )


class ActionConfig(BaseModel):
    """
    Configuration for a single action type.

    Display text is intentionally omitted: the frontend translates ``action``
    by key (``audit_action_{action}`` / ``_description``).
    """

    action: ActionType = Field(
        ..., description="Action type key (e.g., 'user_created')"
    )
    enabled: bool = Field(..., description="Whether this action is currently enabled")
    category: CategoryType = Field(..., description="Category this action belongs to")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "action": "user_created",
                "enabled": True,
                "category": "admin_actions",
            }
        }
    )


class ActionConfigResponse(BaseModel):
    """
    Response model for GET /api/v1/audit/config/actions.
    Contains all 65 actions with their configuration and metadata.
    """

    actions: list[ActionConfig] = Field(
        ..., description="List of all actions with configuration and Swedish metadata"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "actions": [
                    {
                        "action": "user_created",
                        "enabled": True,
                        "category": "admin_actions",
                    },
                    {
                        "action": "user_deleted",
                        "enabled": False,
                        "category": "admin_actions",
                    },
                ]
            }
        }
    )


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

    model_config = ConfigDict(
        json_schema_extra={"example": {"action": "user_created", "enabled": False}}
    )


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

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "updates": [
                    {"action": "user_created", "enabled": False},
                    {"action": "user_deleted", "enabled": False},
                ]
            }
        }
    )
