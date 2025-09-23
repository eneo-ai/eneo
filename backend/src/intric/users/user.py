from datetime import datetime
from enum import Enum
from typing import Optional
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
