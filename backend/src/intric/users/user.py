from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Generic, Optional, TypeVar
from uuid import UUID

from pydantic import EmailStr, Field, computed_field, field_serializer, field_validator

from intric.authentication.auth_models import AccessToken, ApiKey, ApiKeyInDB
from intric.main.models import BaseModel, InDB, ModelId, partial_model
from intric.predefined_roles.predefined_role import (
    PredefinedRoleInDB,
    PredefinedRolePublic,
)
from intric.roles.permissions import Permission
from intric.roles.role import RoleInDB, RolePublic
from intric.tenants.tenant import TenantInDB


class UserState(str, Enum):
    INVITED = "invited"
    ACTIVE = "active"
    INACTIVE = "inactive"
    DELETED = "deleted"


class SortField(str, Enum):
    """Allowed fields for sorting user lists"""
    EMAIL = "email"
    USERNAME = "username"
    CREATED_AT = "created_at"


class SortOrder(str, Enum):
    """Sort direction for user lists"""
    ASC = "asc"
    DESC = "desc"


@dataclass(frozen=True)
class PaginationParams:
    """
    Pagination parameters with validation.

    Implements max depth limit to prevent deep pagination performance issues.
    Max depth of 100 pages ensures bounded query time even with large user bases.

    Examples:
        >>> params = PaginationParams(page=1, page_size=50)
        >>> params.offset  # 0
        >>> params = PaginationParams(page=3, page_size=50)
        >>> params.offset  # 100
    """
    page: int = 1
    page_size: int = 100

    # Constants for validation
    MIN_PAGE: int = 1
    MAX_PAGE: int = 100  # Max depth limit
    MIN_PAGE_SIZE: int = 1
    MAX_PAGE_SIZE: int = 100

    def __post_init__(self):
        """Validate pagination parameters on initialization"""
        if self.page < self.MIN_PAGE:
            raise ValueError(f"page must be >= {self.MIN_PAGE}, got {self.page}")
        if self.page > self.MAX_PAGE:
            raise ValueError(f"page must be <= {self.MAX_PAGE} (max depth limit), got {self.page}")
        if self.page_size < self.MIN_PAGE_SIZE:
            raise ValueError(f"page_size must be >= {self.MIN_PAGE_SIZE}, got {self.page_size}")
        if self.page_size > self.MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be <= {self.MAX_PAGE_SIZE}, got {self.page_size}")

    @property
    def offset(self) -> int:
        """Calculate SQL OFFSET from page number and page size"""
        return (self.page - 1) * self.page_size


@dataclass(frozen=True)
class SearchFilters:
    """
    Search filters for user queries.

    Supports fuzzy matching with case-insensitive ILIKE queries.
    Uses pg_trgm GIN indexes for efficient substring search.

    Examples:
        >>> filters = SearchFilters(email="john")
        >>> filters.has_filters()  # True
        >>> filters = SearchFilters()
        >>> filters.has_filters()  # False
        >>> filters = SearchFilters(state_filter="active")
        >>> filters.has_filters()  # True
    """
    email: str | None = None
    name: str | None = None
    state_filter: str | None = None  # "active" (includes invited) or "inactive"

    def has_filters(self) -> bool:
        """Check if any search filters are active"""
        return self.email is not None or self.name is not None or self.state_filter is not None


@dataclass(frozen=True)
class SortOptions:
    """
    Sort options for user queries.

    Defaults to most recently created users first (created_at DESC).
    Uses composite B-tree indexes for efficient tenant-scoped sorting.

    Examples:
        >>> sort = SortOptions()  # Default: created_at DESC
        >>> sort = SortOptions(field=SortField.EMAIL, order=SortOrder.ASC)
    """
    field: SortField = SortField.CREATED_AT
    order: SortOrder = SortOrder.DESC


T = TypeVar('T')


@dataclass(frozen=True)
class PaginatedResult(Generic[T]):
    """
    Generic paginated result container with metadata.

    Provides pagination metadata for frontend navigation (total_pages, has_next, has_previous).
    Optionally includes counts by state for tab navigation.

    Examples:
        >>> result = PaginatedResult(items=[user1, user2], total_count=50, page=1, page_size=25)
        >>> result.total_pages  # 2
        >>> result.has_next  # True
        >>> result.has_previous  # False
        >>> result.counts  # {'active': 2828, 'inactive': 3}
    """
    items: list[T]
    total_count: int
    page: int
    page_size: int
    counts: dict[str, int] | None = None  # Optional: counts by state for tab display

    @property
    def total_pages(self) -> int:
        """Calculate total number of pages"""
        if self.total_count == 0:
            return 0
        return (self.total_count + self.page_size - 1) // self.page_size

    @property
    def has_next(self) -> bool:
        """Check if there is a next page"""
        return self.page < self.total_pages

    @property
    def has_previous(self) -> bool:
        """Check if there is a previous page"""
        return self.page > 1


class UserBase(BaseModel):
    """
    Leaving off password and salt from base model
    """

    email: EmailStr = Field(
        description="Valid email address",
        examples=["john.doe@municipality.se"]
    )
    username: Optional[str] = Field(
        default=None,
        description="Unique username (optional, will use email prefix if not provided)",
        examples=["john.doe"]
    )

    @field_validator("username")
    def username_is_valid(cls, username: Optional[str]) -> Optional[str]:
        if username is None:
            return
        if len(username) < 1:
            raise ValueError("Username must be 1 characters or more")

        return username

    @field_serializer("email")
    def to_lower(self, email: EmailStr):
        return email.lower()


class UserAdd(UserBase):
    """
    Email, username, and password are required for registering a new user
    """

    id: Optional[UUID] = None
    password: Optional[str] = Field(min_length=7, max_length=100, default=None)
    salt: Optional[str] = None
    used_tokens: int = 0
    email_verified: bool = False
    is_active: bool = True
    state: UserState
    tenant_id: UUID
    quota_limit: Optional[int] = None

    roles: list[ModelId] = []
    predefined_roles: list[ModelId] = []


class UserUpdate(UserBase):
    id: UUID
    email: Optional[EmailStr] = None
    username: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=7, max_length=100)
    used_tokens: Optional[int] = None
    email_verified: Optional[bool] = None
    is_active: Optional[bool] = None
    state: Optional[UserState] = None
    tenant_id: Optional[int] = None
    quota_limit: Optional[int] = None
    salt: Optional[str] = None

    roles: Optional[list[ModelId]] = None
    predefined_roles: list[ModelId] = None


class UserInDBBase(InDB, UserBase):
    tenant_id: UUID


class UserGroupInDBRead(InDB):
    name: str


class UserGroupRead(InDB):
    name: str


class UserInDB(InDB, UserAdd):
    user_groups: list[UserGroupInDBRead] = []
    tenant: TenantInDB
    api_key: Optional[ApiKeyInDB] = None
    roles: list[RoleInDB] = []
    predefined_roles: list[PredefinedRoleInDB] = []
    quota_used: int = 0
    deleted_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when user was soft-deleted (null for active users)"
    )

    @computed_field
    @property
    def modules(self) -> list[str]:
        return [module.name for module in self.tenant.modules]

    @computed_field
    @property
    def user_groups_ids(self) -> set[int]:
        return {user_group.id for user_group in self.user_groups}

    @computed_field
    @property
    def permissions(self) -> set[Permission]:
        permissions_set = set()

        # Add permissions from roles
        for role in self.roles:
            permissions_set.update(role.permissions)

        # Add permissions from predefined roles
        for predefined_role in self.predefined_roles:
            permissions_set.update(predefined_role.permissions)

        return permissions_set


class UserCreated(UserInDB):
    access_token: Optional[AccessToken]
    api_key: Optional[ApiKey]
    roles: list[RoleInDB] = []
    predefined_roles: list[PredefinedRoleInDB] = []


class UserPublicBase(InDB, UserBase):
    quota_used: int = 0


class UserPublic(UserPublicBase):
    truncated_api_key: Optional[str] = None
    quota_limit: Optional[int] = None
    roles: list[RolePublic]
    predefined_roles: list[PredefinedRolePublic]
    user_groups: list[UserGroupRead]


class UserPublicWithAccessToken(UserPublic):
    access_token: AccessToken


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=7, max_length=100)


class UserAddAdmin(UserBase):
    password: Optional[str] = Field(
        min_length=7, max_length=100, default=None,
        description="User password (minimum 7 characters)",
        examples=["SecurePassword123!"]
    )
    quota_limit: Optional[int] = Field(
        description="Storage limit in bytes (minimum 1000 bytes = 1KB)", 
        ge=1e3, default=None,
        examples=[50000000]  # 50MB
    )

    roles: list[ModelId] = Field(
        default=[], 
        description="List of custom role IDs to assign to the user",
        examples=[[]]
    )
    predefined_roles: list[ModelId] = Field(
        default=[],
        description="List of predefined role IDs to assign to the user", 
        examples=[[]]
    )


class UserAddSuperAdmin(UserAddAdmin):
    tenant_id: UUID


class UserAdminView(UserPublicBase):
    used_tokens: int
    email_verified: bool
    quota_limit: Optional[int]
    is_active: bool
    state: UserState

    roles: list[RolePublic]
    predefined_roles: list[PredefinedRolePublic]
    user_groups: list[UserGroupRead]


class UserCreatedAdminView(UserAdminView):
    api_key: ApiKey


class UserUpdatePublic(BaseModel):
    email: Optional[EmailStr] = Field(
        default=None,
        description="New email address (must be unique within tenant)",
        examples=["updated.email@municipality.se"]
    )
    username: Optional[str] = Field(
        default=None,
        description="Username cannot be updated after creation"
    )
    password: Optional[str] = Field(
        default=None, min_length=7, max_length=100,
        description="New password (minimum 7 characters)",
        examples=["NewSecurePassword456!"]
    )
    quota_limit: Optional[int] = Field(
        description="New storage limit in bytes (minimum 1000 bytes = 1KB)", 
        ge=1e3, default=None,
        examples=[100000000]  # 100MB
    )
    roles: Optional[list[ModelId]] = Field(
        default=None,
        description="List of custom role IDs to assign (replaces existing roles)",
        examples=[[]]
    )
    predefined_roles: list[ModelId] = Field(
        default=None,
        description="List of predefined role IDs to assign (replaces existing predefined roles)",
        examples=[[]]
    )
    state: Optional[UserState] = Field(
        default=None,
        description="User state (invited/active/inactive)",
        examples=["active"]
    )


class UserSparse(InDB):
    email: EmailStr
    username: Optional[str] = None

    @field_serializer("email")
    def to_lower(self, email: EmailStr):
        return email.lower()


@partial_model
class PropUserUpdate(BaseModel):
    predefined_role: ModelId
    state: UserState


class PropUserInvite(PropUserUpdate):
    email: EmailStr


class UserProvision(BaseModel):
    zitadel_token: str
