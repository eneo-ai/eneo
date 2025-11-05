from datetime import datetime
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, Field, HttpUrl, field_validator

from intric.users.user import SortField, SortOrder


class PrivacyPolicy(BaseModel):
    url: Optional[HttpUrl] = None


class UserStateListItem(BaseModel):
    """Minimal user information for state-based list operations"""
    username: str = Field(
        description="User's unique username",
        examples=["jane.smith"]
    )
    email: str = Field(
        description="User's email address",
        examples=["jane.smith@municipality.se"]
    )
    state: str = Field(
        description="User's current state",
        examples=["inactive"]
    )
    state_changed_at: datetime = Field(
        description="When the user state was last changed",
        examples=["2025-09-10T08:30:00Z"]
    )


class UserDeletedListItem(BaseModel):
    """User information for deleted users list operations"""
    username: str = Field(
        description="User's unique username",
        examples=["former.employee"]
    )
    email: str = Field(
        description="User's email address",
        examples=["former.employee@municipality.se"]
    )
    state: str = Field(
        description="User's current state (always 'deleted' for this list)",
        examples=["deleted"]
    )
    deleted_at: datetime = Field(
        description="When the user was deleted (for external tracking)",
        examples=["2025-08-15T14:20:00Z"]
    )


class AdminUsersQueryParams(BaseModel):
    """
    Query parameters for admin users list endpoint with pagination and search.

    Implements max depth limit (page <= 100) to prevent deep pagination performance issues.
    Uses pg_trgm GIN indexes for efficient fuzzy email/username search.

    Examples:
        Default (first 100 users, sorted by created_at DESC):
        GET /api/v1/admin/users/

        Custom page size (50 users per page):
        GET /api/v1/admin/users/?page_size=50

        Email search (case-insensitive, partial match):
        GET /api/v1/admin/users/?search_email=john.doe

        Name search:
        GET /api/v1/admin/users/?search_name=emma

        Combined search and pagination:
        GET /api/v1/admin/users/?search_email=@municipality.se&page=2&page_size=50

        Sort by email ascending:
        GET /api/v1/admin/users/?sort_by=email&sort_order=asc
    """
    page: int = Field(
        default=1,
        ge=1,
        le=100,
        description="Page number (1-based). Maximum 100 pages to prevent deep pagination performance issues.",
        examples=[1]
    )
    page_size: int = Field(
        default=100,
        ge=1,
        le=100,
        description="Number of users per page. Maximum 100 to balance performance and usability.",
        examples=[100]
    )
    search_email: Optional[str] = Field(
        default=None,
        description="Search users by email (case-insensitive, partial match). Uses pg_trgm fuzzy matching for efficient substring search.",
        examples=["john.doe", "@municipality.se"]
    )
    search_name: Optional[str] = Field(
        default=None,
        description="Search users by username (case-insensitive, partial match). Uses pg_trgm fuzzy matching.",
        examples=["emma", "anders"]
    )
    sort_by: SortField = Field(
        default=SortField.CREATED_AT,
        description="Field to sort by. Uses composite B-tree indexes for efficient tenant-scoped sorting.",
        examples=["created_at"]
    )
    sort_order: SortOrder = Field(
        default=SortOrder.DESC,
        description="Sort order (ascending or descending)",
        examples=["desc"]
    )

    @field_validator("page")
    @classmethod
    def validate_page(cls, v: int) -> int:
        if v < 1:
            raise ValueError("page must be at least 1")
        if v > 100:
            raise ValueError("page must not exceed 100 (max depth limit)")
        return v

    @field_validator("page_size")
    @classmethod
    def validate_page_size(cls, v: int) -> int:
        if v < 1:
            raise ValueError("page_size must be at least 1")
        if v > 100:
            raise ValueError("page_size must not exceed 100")
        return v

    @field_validator("search_email")
    @classmethod
    def validate_search_email(cls, v: str | None) -> str | None:
        if v is not None:
            trimmed = v.strip()
            if trimmed and len(trimmed) < 3:
                raise ValueError("search_email must be at least 3 characters (prevents inefficient trigram queries)")
            return trimmed if trimmed else None
        return v

    @field_validator("search_name")
    @classmethod
    def validate_search_name(cls, v: str | None) -> str | None:
        if v is not None:
            trimmed = v.strip()
            if trimmed and len(trimmed) < 3:
                raise ValueError("search_name must be at least 3 characters (prevents inefficient trigram queries)")
            return trimmed if trimmed else None
        return v


class PaginationMetadata(BaseModel):
    """
    Pagination metadata for frontend navigation.

    Provides all information needed to build pagination UI (page numbers, next/previous buttons).
    """
    page: int = Field(
        description="Current page number (1-based)",
        examples=[1]
    )
    page_size: int = Field(
        description="Number of items per page",
        examples=[100]
    )
    total_count: int = Field(
        description="Total number of items across all pages",
        examples=[543]
    )
    total_pages: int = Field(
        description="Total number of pages (calculated from total_count and page_size)",
        examples=[6]
    )
    has_next: bool = Field(
        description="Whether there is a next page available",
        examples=[True]
    )
    has_previous: bool = Field(
        description="Whether there is a previous page available",
        examples=[False]
    )


T = TypeVar('T')


class PaginatedUsersResponse(BaseModel, Generic[T]):
    """
    Paginated response for admin users list.

    Provides user data with pagination metadata for efficient large-dataset browsing.
    """
    items: list[T] = Field(
        description="List of users for the current page",
        examples=[[]]
    )
    metadata: PaginationMetadata = Field(
        description="Pagination metadata for navigation"
    )
