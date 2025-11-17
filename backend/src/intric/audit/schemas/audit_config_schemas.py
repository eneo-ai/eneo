"""Pydantic schemas for audit category configuration."""

from pydantic import BaseModel, Field


class CategoryConfig(BaseModel):
    """
    Enriched category configuration with metadata for API responses.
    """
    category: str = Field(..., description="Category name (e.g., 'admin_actions')")
    enabled: bool = Field(..., description="Whether category is currently enabled")
    description: str = Field(..., description="Human-readable description of category")
    action_count: int = Field(..., description="Number of action types in this category")
    example_actions: list[str] = Field(
        ...,
        description="Sample action types (max 3) for UI display"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "category": "admin_actions",
                "enabled": True,
                "description": "User management, role changes, API keys, tenant settings",
                "action_count": 13,
                "example_actions": ["USER_CREATED", "ROLE_DELETED", "API_KEY_GENERATED"]
            }
        }


class CategoryUpdate(BaseModel):
    """
    Represents a category configuration change request.
    """
    category: str = Field(..., description="Category name to update")
    enabled: bool = Field(..., description="New enabled state")

    class Config:
        json_schema_extra = {
            "example": {
                "category": "admin_actions",
                "enabled": False
            }
        }


class AuditConfigResponse(BaseModel):
    """
    Response model for GET /api/v1/audit/config.
    Contains all 7 categories with metadata.
    """
    categories: list[CategoryConfig] = Field(
        ...,
        description="List of all audit categories with configuration and metadata"
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
                        "example_actions": ["USER_CREATED", "ROLE_DELETED", "API_KEY_GENERATED"]
                    },
                    {
                        "category": "user_actions",
                        "enabled": True,
                        "description": "Assistant, space, app operations, templates, model configs",
                        "action_count": 28,
                        "example_actions": ["ASSISTANT_CREATED", "SPACE_DELETED", "APP_EXECUTED"]
                    }
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
        max_length=7
    )

    class Config:
        json_schema_extra = {
            "example": {
                "updates": [
                    {"category": "admin_actions", "enabled": False},
                    {"category": "file_operations", "enabled": False}
                ]
            }
        }
