from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Literal, Optional
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    ValidationInfo,
    field_validator,
)

from intric.main.config import get_settings


class JWTMeta(BaseModel):
    iss: str = get_settings().jwt_issuer  # who issued it
    aud: str = get_settings().jwt_audience  # who it's intended for
    iat: float = datetime.timestamp(datetime.utcnow())  # issued at time
    exp: float = datetime.timestamp(
        datetime.utcnow() + timedelta(minutes=get_settings().jwt_expiry_time)
    )  # expiry time


class JWTCreds(BaseModel):
    """How we'll identify users"""

    sub: EmailStr
    username: Optional[str] = None


class JWTPayload(JWTMeta, JWTCreds):
    """
    JWT Payload right before it's encoded - combine meta and username
    """

    pass


class AccessToken(BaseModel):
    access_token: str
    token_type: str


class ApiKeyType(str, Enum):
    PK = "pk_"
    SK = "sk_"


class ApiKeyUserRelation(str, Enum):
    OWNER = "owner"
    CREATOR = "creator"


class ApiKeySearchMatchReason(str, Enum):
    EXACT_SECRET = "exact_secret"
    KEY_SUFFIX = "key_suffix"
    NAME_OR_DESCRIPTION = "name_or_description"
    OWNER = "owner"
    CREATOR = "creator"


class ApiKeyPermission(str, Enum):
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


# Centralized ordering — used by both policy validation and runtime enforcement
PERMISSION_LEVEL_ORDER: dict[str, int] = {
    "none": 0,
    "read": 1,
    "write": 2,
    "admin": 3,
}


METHOD_PERMISSION_MAP: dict[str, str] = {
    "GET": "read",
    "HEAD": "read",
    "OPTIONS": "read",
    "POST": "write",
    "PUT": "write",
    "PATCH": "write",
    "DELETE": "admin",
}


class ResourcePermissionLevel(str, Enum):
    NONE = "none"
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


class ResourcePermissions(BaseModel):
    """Per-resource-type permission overrides. Each level must not exceed the key's simple permission."""

    assistants: ResourcePermissionLevel = ResourcePermissionLevel.NONE
    apps: ResourcePermissionLevel = ResourcePermissionLevel.NONE
    spaces: ResourcePermissionLevel = ResourcePermissionLevel.NONE
    knowledge: ResourcePermissionLevel = ResourcePermissionLevel.NONE

    model_config = ConfigDict(extra="forbid")


class ApiKeyScopeType(str, Enum):
    TENANT = "tenant"
    SPACE = "space"
    ASSISTANT = "assistant"
    APP = "app"


class ApiKeyNotificationTargetType(str, Enum):
    KEY = "key"
    ASSISTANT = "assistant"
    APP = "app"
    SPACE = "space"


class ApiKeyState(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"
    EXPIRED = "expired"


class ApiKeyStateReasonCode(str, Enum):
    SECURITY_CONCERN = "security_concern"
    ABUSE_DETECTED = "abuse_detected"
    USER_REQUEST = "user_request"
    ADMIN_ACTION = "admin_action"
    POLICY_VIOLATION = "policy_violation"
    KEY_COMPROMISED = "key_compromised"
    USER_OFFBOARDING = "user_offboarding"
    ROTATION_COMPLETED = "rotation_completed"
    SCOPE_REMOVED = "scope_removed"
    OTHER = "other"


class ApiKeyHashVersion(str, Enum):
    HMAC_SHA256 = "hmac_sha256"
    SHA256 = "sha256"


def compute_effective_state(
    *,
    revoked_at: Optional[datetime],
    suspended_at: Optional[datetime],
    expires_at: Optional[datetime],
    now: Optional[datetime] = None,
) -> ApiKeyState:
    if revoked_at is not None:
        return ApiKeyState.REVOKED
    if expires_at is not None:
        comparison_time = now or datetime.now(timezone.utc)
        if comparison_time.tzinfo is None:
            comparison_time = comparison_time.replace(tzinfo=timezone.utc)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < comparison_time:
            return ApiKeyState.EXPIRED
    if suspended_at is not None:
        return ApiKeyState.SUSPENDED
    return ApiKeyState.ACTIVE


class ApiKeyStateChangeRequest(BaseModel):
    reason_code: Optional[ApiKeyStateReasonCode] = None
    reason_text: Optional[str] = None


class ApiKeyCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    key_type: ApiKeyType
    permission: ApiKeyPermission = ApiKeyPermission.READ
    scope_type: ApiKeyScopeType
    scope_id: Optional[UUID] = None
    allowed_origins: Optional[list[str]] = None
    allowed_ips: Optional[list[str]] = None
    expires_at: Optional[datetime] = None
    rate_limit: Optional[int] = None
    resource_permissions: Optional[ResourcePermissions] = None


class ApiKeyUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permission: Optional[ApiKeyPermission] = None
    allowed_origins: Optional[list[str]] = None
    allowed_ips: Optional[list[str]] = None
    expires_at: Optional[datetime] = None
    rate_limit: Optional[int] = None
    resource_permissions: Optional[ResourcePermissions] = None


class ApiKeyExactLookupRequest(BaseModel):
    secret: str


class ApiKeyUserSnapshot(BaseModel):
    id: UUID
    email: Optional[str] = None
    username: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ApiKeyV2(BaseModel):
    id: UUID
    owner_user_id: UUID
    key_prefix: str
    key_suffix: str
    name: str
    description: Optional[str] = None
    key_type: ApiKeyType
    permission: ApiKeyPermission
    scope_type: ApiKeyScopeType
    scope_id: Optional[UUID] = None
    allowed_origins: Optional[list[str]] = None
    allowed_ips: Optional[list[str]] = None
    resource_permissions: Optional[ResourcePermissions] = None
    state: ApiKeyState
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    revoked_reason_code: Optional[ApiKeyStateReasonCode] = None
    revoked_reason_text: Optional[str] = None
    suspended_at: Optional[datetime] = None
    suspended_reason_code: Optional[ApiKeyStateReasonCode] = None
    suspended_reason_text: Optional[str] = None
    rotation_grace_until: Optional[datetime] = None
    rate_limit: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    rotated_from_key_id: Optional[UUID] = None
    created_by_user_id: Optional[UUID] = None
    owner_user: Optional[ApiKeyUserSnapshot] = None
    created_by_user: Optional[ApiKeyUserSnapshot] = None
    search_match_reasons: Optional[list[ApiKeySearchMatchReason]] = None

    model_config = ConfigDict(from_attributes=True)


class ApiKeyV2InDB(ApiKeyV2):
    tenant_id: UUID
    created_by_key_id: Optional[UUID] = None
    delegation_depth: int = 0
    key_hash: str
    hash_version: str

    model_config = ConfigDict(from_attributes=True)


class ApiKeyPolicyUpdate(BaseModel):
    max_delegation_depth: Optional[int] = None
    revocation_cascade_enabled: Optional[bool] = None
    require_expiration: Optional[bool] = None
    max_expiration_days: Optional[int] = None
    auto_expire_unused_days: Optional[int] = None
    max_rate_limit_override: Optional[int] = None

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "max_delegation_depth",
        "max_expiration_days",
        "auto_expire_unused_days",
        "max_rate_limit_override",
    )
    @classmethod
    def _validate_positive(
        cls, value: Optional[int], info: ValidationInfo
    ) -> Optional[int]:
        if value is None:
            return value
        if value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer.")
        return value


class ApiKeyPolicyResponse(BaseModel):
    max_delegation_depth: Optional[int] = None
    revocation_cascade_enabled: Optional[bool] = None
    require_expiration: Optional[bool] = None
    max_expiration_days: Optional[int] = None
    auto_expire_unused_days: Optional[int] = None
    max_rate_limit_override: Optional[int] = None

    model_config = ConfigDict(extra="ignore")


def _validate_day_values(days: list[int], field_name: str) -> list[int]:
    if not days:
        raise ValueError(f"{field_name} must contain at least one day value.")
    normalized = sorted(set(days), reverse=True)
    for day in normalized:
        if day <= 0:
            raise ValueError(f"{field_name} values must be positive integers.")
    return normalized


class ApiKeyNotificationPreferencesResponse(BaseModel):
    enabled: bool = False
    days_before_expiry: list[int] = Field(default_factory=lambda: [30, 14, 7, 3, 1])
    auto_follow_published_assistants: bool = False
    auto_follow_published_apps: bool = False

    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("days_before_expiry")
    @classmethod
    def _validate_days_before_expiry(cls, value: list[int]) -> list[int]:
        return _validate_day_values(value, "days_before_expiry")


class ApiKeyNotificationPreferencesUpdate(BaseModel):
    enabled: Optional[bool] = None
    days_before_expiry: Optional[list[int]] = None
    auto_follow_published_assistants: Optional[bool] = None
    auto_follow_published_apps: Optional[bool] = None

    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("days_before_expiry")
    @classmethod
    def _validate_days_before_expiry(
        cls, value: Optional[list[int]]
    ) -> Optional[list[int]]:
        if value is None:
            return value
        return _validate_day_values(value, "days_before_expiry")


class ApiKeyNotificationSubscription(BaseModel):
    target_type: ApiKeyNotificationTargetType
    target_id: UUID

    model_config = ConfigDict(extra="forbid", strict=True)


class ApiKeyNotificationSubscriptionListResponse(BaseModel):
    items: list[ApiKeyNotificationSubscription]

    model_config = ConfigDict(extra="forbid", strict=True)


class ApiKeyNotificationPolicyResponse(BaseModel):
    enabled: bool = True
    default_days_before_expiry: list[int] = Field(
        default_factory=lambda: [30, 14, 7, 3, 1]
    )
    max_days_before_expiry: Optional[int] = 365
    allow_auto_follow_published_assistants: bool = False
    allow_auto_follow_published_apps: bool = False

    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("default_days_before_expiry")
    @classmethod
    def _validate_default_days_before_expiry(cls, value: list[int]) -> list[int]:
        return _validate_day_values(value, "default_days_before_expiry")

    @field_validator("max_days_before_expiry")
    @classmethod
    def _validate_max_days_before_expiry(
        cls, value: Optional[int], info: ValidationInfo
    ) -> Optional[int]:
        if value is None:
            return value
        if value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer.")
        return value


class ApiKeyNotificationPolicyUpdate(BaseModel):
    enabled: Optional[bool] = None
    default_days_before_expiry: Optional[list[int]] = None
    max_days_before_expiry: Optional[int] = None
    allow_auto_follow_published_assistants: Optional[bool] = None
    allow_auto_follow_published_apps: Optional[bool] = None

    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("default_days_before_expiry")
    @classmethod
    def _validate_default_days_before_expiry(
        cls, value: Optional[list[int]]
    ) -> Optional[list[int]]:
        if value is None:
            return value
        return _validate_day_values(value, "default_days_before_expiry")

    @field_validator("max_days_before_expiry")
    @classmethod
    def _validate_max_days_before_expiry(
        cls, value: Optional[int], info: ValidationInfo
    ) -> Optional[int]:
        if value is None:
            return value
        if value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer.")
        return value


class SuperApiKeyStatus(BaseModel):
    super_api_key_configured: bool
    super_duper_api_key_configured: bool

    model_config = ConfigDict(extra="forbid")


class ApiKeyListResponse(BaseModel):
    """Response model for the API key list endpoint. Uses Optional total_count
    so non-admin users get null instead of an expensive COUNT query."""

    items: list[ApiKeyV2]
    limit: Optional[int] = None
    next_cursor: Optional[datetime] = None
    previous_cursor: Optional[datetime] = None
    total_count: Optional[int] = None

    @property
    def count(self) -> int:
        return len(self.items)


class ApiKeyCreationConstraints(BaseModel):
    """Fields relevant to key creation UX, from tenant policy."""

    require_expiration: bool = False
    max_expiration_days: Optional[int] = None
    max_rate_limit: Optional[int] = None


class ExpiringKeySummaryItem(BaseModel):
    """Lightweight summary of a single expiring API key."""

    id: UUID
    name: str
    key_suffix: Optional[str] = None
    scope_type: ApiKeyScopeType
    scope_id: Optional[UUID] = None
    expires_at: datetime
    suspended_at: Optional[datetime] = None
    severity: Literal["notice", "warning", "urgent", "expired"]


class ExpiringKeysSummary(BaseModel):
    """Aggregated expiring-key data for banners and the notification bell."""

    total_count: int
    counts_by_severity: dict[str, int]
    earliest_expiration: Optional[datetime] = None
    items: list[ExpiringKeySummaryItem]
    truncated: bool
    generated_at: datetime


class ApiKeyCreatedResponse(BaseModel):
    api_key: ApiKeyV2
    secret: str


class ApiKeyExactLookupResponse(BaseModel):
    api_key: ApiKeyV2
    match_reason: ApiKeySearchMatchReason = ApiKeySearchMatchReason.EXACT_SECRET


class ApiKeyUsageEvent(BaseModel):
    id: UUID
    timestamp: datetime
    action: str
    outcome: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    request_id: Optional[UUID] = None
    request_path: Optional[str] = None
    method: Optional[str] = None
    origin: Optional[str] = None
    error_message: Optional[str] = None


class ApiKeyUsageSummary(BaseModel):
    total_events: int
    used_events: int
    auth_failed_events: int
    last_seen_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    sampled_used_events: bool = False


class ApiKeyUsageResponse(BaseModel):
    summary: ApiKeyUsageSummary
    items: list[ApiKeyUsageEvent]
    limit: int
    next_cursor: Optional[datetime] = None


class ApiKeyPublic(BaseModel):
    truncated_key: str


class ApiKey(ApiKeyPublic):
    key: str


class ApiKeyCreated(ApiKey):
    hashed_key: str


class ApiKeyInDB(ApiKey):
    user_id: Optional[UUID]
    assistant_id: Optional[UUID]

    model_config = ConfigDict(from_attributes=True)


class CreateUserResponse(BaseModel):
    token: AccessToken
    api_key: ApiKey


class OpenIdConnectLogin(BaseModel):
    code: str
    code_verifier: str
    redirect_uri: str
    client_id: str
    grant_type: str = "authorization_code"
    scope: str = "openid"
    nonce: Optional[str] = None
