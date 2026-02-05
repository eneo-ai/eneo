from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, ValidationInfo, field_validator

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


class ApiKeyPermission(str, Enum):
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


class ApiKeyScopeType(str, Enum):
    TENANT = "tenant"
    SPACE = "space"
    ASSISTANT = "assistant"
    APP = "app"


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


class ApiKeyUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    allowed_origins: Optional[list[str]] = None
    allowed_ips: Optional[list[str]] = None
    expires_at: Optional[datetime] = None
    rate_limit: Optional[int] = None


class ApiKeyV2(BaseModel):
    id: UUID
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

    model_config = ConfigDict(from_attributes=True)


class ApiKeyV2InDB(ApiKeyV2):
    tenant_id: UUID
    owner_user_id: UUID
    created_by_user_id: Optional[UUID] = None
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


class SuperApiKeyStatus(BaseModel):
    super_api_key_configured: bool
    super_duper_api_key_configured: bool

    model_config = ConfigDict(extra="forbid")


class ApiKeyCreatedResponse(BaseModel):
    api_key: ApiKeyV2
    secret: str


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
