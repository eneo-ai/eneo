from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Literal, Optional, cast
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    ValidationInfo,
    field_validator,
    model_validator,
)

from intric.main.config import get_settings


class JWTMeta(BaseModel):
    iss: str = get_settings().jwt_issuer  # who issued it
    aud: str = get_settings().jwt_audience  # who it's intended for
    iat: float = datetime.timestamp(datetime.now(timezone.utc))  # issued at time
    exp: float = datetime.timestamp(
        datetime.now(timezone.utc) + timedelta(minutes=get_settings().jwt_expiry_time)
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


class ApiKeyOwnership(str, Enum):
    USER = "user"
    SERVICE = "service"


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


class ApiKeyNotificationSubscriptionSource(str, Enum):
    MANUAL = "manual"
    AUTO_FOLLOW = "auto_follow"


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
    rotation_grace_until: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> ApiKeyState:
    if revoked_at is not None:
        return ApiKeyState.REVOKED
    comparison_time = now or datetime.now(timezone.utc)
    if comparison_time.tzinfo is None:
        comparison_time = comparison_time.replace(tzinfo=timezone.utc)
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < comparison_time:
            return ApiKeyState.EXPIRED
    if rotation_grace_until is not None:
        if rotation_grace_until.tzinfo is None:
            rotation_grace_until = rotation_grace_until.replace(tzinfo=timezone.utc)
        if rotation_grace_until < comparison_time:
            return ApiKeyState.REVOKED
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
    ownership: ApiKeyOwnership = ApiKeyOwnership.USER
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
    ownership: ApiKeyOwnership = ApiKeyOwnership.USER
    owner_user_id: Optional[UUID] = None
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


def _coerce_legacy_notification_day_value(raw: Any) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, float):
        if raw.is_integer() and raw > 0:
            return int(raw)
        return None
    if isinstance(raw, str):
        try:
            parsed = int(raw.strip())
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None
    if isinstance(raw, list):
        candidates: list[int] = []
        raw_items = cast(list[object], raw)
        for raw_item in raw_items:
            item: Any = raw_item
            value = _coerce_legacy_notification_day_value(item)
            if value is not None:
                candidates.append(value)
        return max(candidates) if candidates else None
    return None


def normalize_notification_day_value(
    raw: Any, *, default: int | None = None
) -> int | None:
    value = _coerce_legacy_notification_day_value(raw)
    if value is not None:
        return value
    return default


def normalize_notification_policy_payload(raw_policy: Any) -> dict[str, Any]:
    if not isinstance(raw_policy, dict):
        return {}

    normalized_policy: dict[str, Any] = dict(cast(dict[str, Any], raw_policy))
    max_days = normalize_notification_day_value(
        normalized_policy.get("max_days_before_expiry")
    )
    if max_days is None:
        normalized_policy.pop("max_days_before_expiry", None)
    else:
        normalized_policy["max_days_before_expiry"] = max_days

    default_days = normalize_notification_day_value(
        normalized_policy.get("default_days_before_expiry"),
        default=30,
    )
    if default_days is None:
        default_days = 30
    if max_days is not None:
        default_days = min(default_days, max_days)
    normalized_policy["default_days_before_expiry"] = default_days
    return normalized_policy


def _validate_day_value(day: int, field_name: str) -> int:
    if day <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return day


class ApiKeyNotificationPreferencesResponse(BaseModel):
    enabled: bool = False
    days_before_expiry: int = 30
    auto_follow_published_assistants: bool = False
    auto_follow_published_apps: bool = False

    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("days_before_expiry")
    @classmethod
    def _validate_days_before_expiry(cls, value: int) -> int:
        return _validate_day_value(value, "days_before_expiry")


class ApiKeyNotificationPreferencesUpdate(BaseModel):
    enabled: Optional[bool] = None
    days_before_expiry: Optional[int] = None
    auto_follow_published_assistants: Optional[bool] = None
    auto_follow_published_apps: Optional[bool] = None

    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("days_before_expiry")
    @classmethod
    def _validate_days_before_expiry(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return value
        return _validate_day_value(value, "days_before_expiry")


class ApiKeyNotificationSubscription(BaseModel):
    target_type: ApiKeyNotificationTargetType
    target_id: UUID

    model_config = ConfigDict(extra="forbid", strict=True)


class ApiKeyNotificationSubscriptionListResponse(BaseModel):
    items: list[ApiKeyNotificationSubscription]

    model_config = ConfigDict(extra="forbid", strict=True)


class ApiKeyNotificationPolicyResponse(BaseModel):
    enabled: bool = True
    default_days_before_expiry: int = 30
    max_days_before_expiry: Optional[int] = 365
    allow_auto_follow_published_assistants: bool = False
    allow_auto_follow_published_apps: bool = False

    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("default_days_before_expiry")
    @classmethod
    def _validate_default_days_before_expiry(cls, value: int) -> int:
        return _validate_day_value(value, "default_days_before_expiry")

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

    @model_validator(mode="after")
    def _validate_day_bounds(self) -> "ApiKeyNotificationPolicyResponse":
        if (
            self.max_days_before_expiry is not None
            and self.default_days_before_expiry > self.max_days_before_expiry
        ):
            raise ValueError(
                "default_days_before_expiry must be less than or equal to max_days_before_expiry."
            )
        return self


class ApiKeyNotificationPolicyUpdate(BaseModel):
    enabled: Optional[bool] = None
    default_days_before_expiry: Optional[int] = None
    max_days_before_expiry: Optional[int] = None
    allow_auto_follow_published_assistants: Optional[bool] = None
    allow_auto_follow_published_apps: Optional[bool] = None

    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("default_days_before_expiry")
    @classmethod
    def _validate_default_days_before_expiry(
        cls, value: Optional[int]
    ) -> Optional[int]:
        if value is None:
            return value
        return _validate_day_value(value, "default_days_before_expiry")

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

    @model_validator(mode="after")
    def _validate_day_bounds(self) -> "ApiKeyNotificationPolicyUpdate":
        if (
            self.max_days_before_expiry is not None
            and self.default_days_before_expiry is not None
            and self.default_days_before_expiry > self.max_days_before_expiry
        ):
            raise ValueError(
                "default_days_before_expiry must be less than or equal to max_days_before_expiry."
            )
        return self


class SuperApiKeyStatus(BaseModel):
    super_api_key_configured: bool
    super_duper_api_key_configured: bool
    super_api_key_using_legacy: bool = False
    super_duper_api_key_using_legacy: bool = False

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
    model_config = ConfigDict(from_attributes=True)
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
