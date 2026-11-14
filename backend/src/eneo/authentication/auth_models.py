import base64
import binascii
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Literal, Optional
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    ValidationInfo,
    field_serializer,
    field_validator,
)

from eneo.audit.domain.actor_types import ActorType
from eneo.widgets.domain.visitor import WidgetVisitorContext

if TYPE_CHECKING:
    from eneo.users.user import UserInDB


WIDGET_MCP_AUDIENCE = "eneo:widget-internal-mcp"


class ScopedMcpClaims(BaseModel):
    """Verified scope carried across the internal MCP HTTP boundary."""

    model_config = ConfigDict(frozen=True)

    aud: str
    assistant_id: UUID
    mcp_server_id: UUID | None = None
    widget_visitor: WidgetVisitorContext | None = None


class JWTMeta(BaseModel):
    # Received tokens must carry their own metadata; never invent missing claims.
    iss: str
    aud: str
    iat: float
    exp: float


# A browser session id: 256 random bits, as secrets.token_urlsafe(32) writes them.
SESSION_ID_PATTERN = r"^[A-Za-z0-9_-]{43}$"
# A browser session's stable id, in the one form str(UUID) writes.
SESSION_REF_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


class JWTCreds(BaseModel):
    """Immutable Eneo session identity, shared by API, MCP and module tokens."""

    token_version: Literal[2]
    user_id: UUID
    tenant_id: UUID
    credential_version: int = Field(ge=0, strict=True)
    # Minted only by the local password login ("password"); decoded as a
    # plain string so a value added by a newer deployment never makes an
    # older one reject the token. See eneo.users.password_lifecycle.
    auth_method: Optional[str] = None
    # Retained as descriptive claims for clients; never used to resolve a user.
    sub: EmailStr
    username: Optional[str] = None
    # The server-side browser session (eneo.authentication.
    # browser_session_service). Only starting a session adds it to a token,
    # so minting never dumps it. A present claim is a session id: null or any
    # other value is refused, never read as a token without one.
    sid: Optional[str] = Field(
        default=None, exclude=True, strict=True, pattern=SESSION_ID_PATTERN
    )
    # The same session's stable, non-secret id (browser_sessions.id), signed
    # beside sid; tokens issued before it existed carry sid alone. Like sid,
    # never dumped, and a present claim must be the form sign-in writes.
    session_ref: Optional[UUID] = Field(default=None, exclude=True)

    @field_validator("sid", mode="before")
    @classmethod
    def _refuse_null_sid(cls, value: object) -> object:
        if value is None:
            raise ValueError("sid must not be null")
        return value

    @field_validator("session_ref", mode="before")
    @classmethod
    def _refuse_other_session_ref_forms(cls, value: object) -> object:
        if isinstance(value, UUID):
            return value
        if not isinstance(value, str) or not re.fullmatch(SESSION_REF_PATTERN, value):
            raise ValueError("session_ref must be a session id")
        return value


class JWTPayload(JWTMeta, JWTCreds):
    """Verified Eneo session claims, including the required identity version."""

    pass


CredentialKind = Literal["browser_session", "derived", "bearer", "api_key"]


class CredentialFacts(BaseModel):
    """What the credential a request was admitted with says about it.

    The adapter that resolves the credential sets it on the user; the checks
    that depend on how the request authenticated read it. Request-scoped:
    never persisted or returned.

    - ``browser_session``: an Eneo token with ``sid``; ``session`` holds its
      verified claims.
    - ``derived``: a token minted from another credential, a scoped MCP
      token or a module token.
    - ``bearer``: any other Eneo token, or a provider's access token.
    - ``api_key``: a user or service API key.

    ``session_ref`` names the browser session the credential belongs to, and
    ``auth_method`` is the token's claim ("password" for a password sign-in).
    """

    model_config = ConfigDict(frozen=True)

    kind: CredentialKind
    session_ref: Optional[UUID] = None
    auth_method: Optional[str] = None
    session: Optional[JWTPayload] = None

    @classmethod
    def of_token(cls, payload: JWTPayload) -> "CredentialFacts":
        """An Eneo token's facts: a browser session when it carries ``sid``."""
        return cls(
            kind="browser_session" if payload.sid is not None else "bearer",
            session_ref=payload.session_ref,
            auth_method=payload.auth_method,
            session=payload if payload.sid is not None else None,
        )


class AccessToken(BaseModel):
    access_token: str
    token_type: str


class BrowserSessionExtension(BaseModel):
    """The renewed browser session; its token travels only in the cookie."""

    generation: str = Field(
        description="The session's `Eneo-Session-Generation`, which a renewal keeps."
    )
    expires_in: int = Field(
        ge=0, description="Whole seconds until the renewed session ends."
    )


class ApiKeyOwnership(str, Enum):
    USER = "user"
    SERVICE = "service"


def is_widget_visitor(user: object) -> bool:
    """Is the request authenticated as an anonymous widget visitor?

    Visitors resolve to a synthetic UserInDB carrying ``active_widget``; they
    own sessions by widget + visitor id and never reach user-keyed storage.
    """
    return getattr(user, "active_widget", None) is not None


def is_service_api_key(user: "UserInDB") -> bool:
    """Single source of truth: is the request authenticated via a service API key?

    Service keys resolve to a synthetic UserInDB with no roles. Callers that
    need to bypass role-based gates (because service keys authorize via
    scope+permission instead) should use this check.

    Accepts any user-like object — raw SQLAlchemy `Users` rows (e.g. from
    test fixtures constructing a SpaceActor directly) lack `active_api_key`
    entirely, so the getattr guard avoids AttributeError and correctly
    reports "not a service key" for those paths.
    """
    key = getattr(user, "active_api_key", None)
    if key is None:
        return False
    return key.ownership == ApiKeyOwnership.SERVICE


def audit_actor_for(user: "UserInDB") -> tuple[UUID | None, ActorType]:
    """Resolve (actor_id, actor_type) for an audit_log entry on this request.

    Service keys have no real user row — passing the synthetic user.id into
    audit_log.actor_id (FK to users.id) would FK-violate. Mirror the gating
    pattern used by user_service._log_api_key_used: emit (None, SYSTEM) for
    service keys, (user.id, USER) for real users.

    A widget visitor is synthetic too (``build_visitor_user``): its id is a
    pseudonymous visitor id, not a users row, so it gets its own actor type
    and no actor_id. The entry's metadata carries the visitor id. Decided on
    the context object itself, so a user double with a truthy attribute of
    that name is still audited as a user.
    """
    if isinstance(getattr(user, "active_widget", None), WidgetVisitorContext):
        return None, ActorType.WIDGET_VISITOR
    if is_service_api_key(user):
        return None, ActorType.SYSTEM
    return user.id, ActorType.USER


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
    """Per-resource-type permission overrides for API keys.

    For sk_ keys, the top-level ``permission`` field is derived automatically
    as the maximum configured level by
    :func:`derive_permission_from_resource_permissions`.  pk_ keys may use the
    same shape, but policy validation caps each resource at ``read``.
    """

    assistants: ResourcePermissionLevel = ResourcePermissionLevel.NONE
    apps: ResourcePermissionLevel = ResourcePermissionLevel.NONE
    spaces: ResourcePermissionLevel = ResourcePermissionLevel.NONE
    knowledge: ResourcePermissionLevel = ResourcePermissionLevel.NONE
    conversations: ResourcePermissionLevel = ResourcePermissionLevel.NONE
    files: ResourcePermissionLevel = ResourcePermissionLevel.NONE
    jobs: ResourcePermissionLevel = ResourcePermissionLevel.NONE
    prompts: ResourcePermissionLevel = ResourcePermissionLevel.NONE

    model_config = ConfigDict(extra="forbid")


RESOURCE_PERMISSION_FIELDS: tuple[str, ...] = (
    "assistants",
    "apps",
    "spaces",
    "knowledge",
    "conversations",
    "files",
    "jobs",
    "prompts",
)


PK_FORBIDDEN_RESOURCE_FIELDS: tuple[str, ...] = ("jobs", "prompts")


_LEVEL_TO_PERMISSION: dict[int, ApiKeyPermission] = {
    0: ApiKeyPermission.READ,
    1: ApiKeyPermission.READ,
    2: ApiKeyPermission.WRITE,
    3: ApiKeyPermission.ADMIN,
}


def derive_permission_from_resource_permissions(
    rp: ResourcePermissions,
) -> ApiKeyPermission:
    """Compute the effective permission ceiling from fine-grained resource permissions.

    Returns the highest permission level found across all resource types.
    If all resource types are ``none``, defaults to ``read``.
    """
    max_level = max(
        PERMISSION_LEVEL_ORDER.get(getattr(rp, field).value, 0)
        for field in RESOURCE_PERMISSION_FIELDS
    )
    return _LEVEL_TO_PERMISSION.get(max_level, ApiKeyPermission.READ)


def default_public_resource_permissions() -> ResourcePermissions:
    """Safe default allowlist for newly created browser/public keys."""
    return ResourcePermissions(
        assistants=ResourcePermissionLevel.READ,
        apps=ResourcePermissionLevel.READ,
    )


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
        if rotation_grace_until <= comparison_time:
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


class ApiKeyExtendRequest(BaseModel):
    expires_at: Optional[datetime] = None


class ApiKeyRotateRequest(BaseModel):
    update_expiration: bool = False
    expires_at: Optional[datetime] = None
    disable_grace_period: bool = False


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

    @field_serializer("resource_permissions")
    def _serialize_resource_permissions(
        self, resource_permissions: ResourcePermissions | None
    ) -> dict[str, str] | None:
        if resource_permissions is None:
            return None
        return resource_permissions.model_dump(mode="json", exclude_unset=True)


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
    require_tenant_allowed_origin: bool = True
    require_expiration: Optional[bool] = None
    max_expiration_days: Optional[int] = None
    auto_expire_unused_days: Optional[int] = None
    max_rate_limit_override: Optional[int] = None
    rotation_grace_hours: Optional[int] = None

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

    @field_validator("rotation_grace_hours")
    @classmethod
    def _validate_non_negative(
        cls, value: Optional[int], info: ValidationInfo
    ) -> Optional[int]:
        if value is None:
            return value
        if value < 0:
            raise ValueError(f"{info.field_name} must be zero or a positive integer.")
        return value


class ApiKeyPolicyResponse(BaseModel):
    max_delegation_depth: Optional[int] = None
    revocation_cascade_enabled: Optional[bool] = None
    require_tenant_allowed_origin: bool = True
    require_expiration: Optional[bool] = None
    max_expiration_days: Optional[int] = None
    auto_expire_unused_days: Optional[int] = None
    max_rate_limit_override: Optional[int] = None
    rotation_grace_hours: Optional[int] = None

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

    model_config = ConfigDict(extra="forbid")


class ApiKeyListResponse(BaseModel):
    """Response model for the API key list endpoint. Uses Optional total_count
    so non-admin users get null instead of an expensive COUNT query."""

    items: list[ApiKeyV2]
    limit: Optional[int] = None
    next_cursor: Optional[str] = None
    previous_cursor: Optional[str] = None
    total_count: Optional[int] = None

    @property
    def count(self) -> int:
        return len(self.items)


class ApiKeyListCursor(BaseModel):
    """Opaque, total-order position in the API-key list.

    ``created_at`` alone is not unique. Pairing it with the primary key makes
    forward and backward keyset pagination deterministic even when several
    keys were created in the same transaction. Legacy timestamp cursors remain
    readable during rollout, while every newly emitted cursor uses this v1
    representation.
    """

    created_at: datetime
    key_id: UUID | None = None

    model_config = ConfigDict(frozen=True)

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    def serialize(self) -> str:
        encoded = base64.urlsafe_b64encode(self.model_dump_json().encode()).decode()
        return f"v1.{encoded.rstrip('=')}"

    @classmethod
    def deserialize(cls, value: str) -> "ApiKeyListCursor":
        if not value.startswith("v1."):
            try:
                legacy_timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("Invalid API key cursor.") from exc
            return cls(created_at=legacy_timestamp)

        encoded = value.removeprefix("v1.")
        padding = "=" * (-len(encoded) % 4)
        try:
            payload = base64.b64decode(
                encoded + padding,
                altchars=b"-_",
                validate=True,
            )
            return cls.model_validate_json(payload)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Invalid API key cursor.") from exc


class ApiKeyCreationConstraints(BaseModel):
    """Tenant policy limits for key forms and notification preferences."""

    notification_policy: ApiKeyNotificationPolicyResponse
    require_expiration: bool = False
    max_expiration_days: Optional[int] = None
    max_rate_limit: Optional[int] = None
    rotation_grace_hours: int = 24


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


def _is_verified_claim(value: object) -> bool:
    # OIDC defines email_verified as a JSON boolean. Some IdPs (e.g. Nexus
    # Digital Access) can only emit claims as text, so the string forms of a
    # positive value are accepted as a compatibility deviation. Nothing else
    # counts as verified.
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1"}
    return False


# The claims that can vouch for the standard email, in order. The first one the
# provider sends (not null) decides, so an explicit negative never falls
# through to the next.
DEFAULT_EMAIL_VERIFIED_CLAIMS = ("email_verified", "xms_edov")


class FederatedIdentity(BaseModel):
    """Email identity extracted only after the OIDC token has been validated.

    Issuer, audience, subject claim and subject are the key an account is
    bound to (``identity_bindings``).
    """

    model_config = ConfigDict(frozen=True)

    issuer: str = Field(min_length=1)
    # The verified audience the subject belongs to: the client id of a browser
    # sign-in's ID token (aud/azp), or the accepted API audience of a
    # provider's access token. Never invented for a path that proves neither.
    audience: str = Field(min_length=1)
    # The claim the subject was read from. Another claim's values are another
    # namespace: the same value there may name someone else.
    subject_claim: str = Field(default="sub", min_length=1)
    subject: str = Field(min_length=1)
    email: EmailStr
    email_verified: bool = Field(strict=True)

    @classmethod
    def from_claims(
        cls,
        claims: Mapping[str, object],
        *,
        issuer: str,
        audience: str,
        # The claim that names the person: ``sub`` unless the provider's
        # claims mapping names a stable id claim instead.
        subject_claim: str = "sub",
        email_claim: str = "email",
        email_verified_claims: Sequence[str] = DEFAULT_EMAIL_VERIFIED_CLAIMS,
    ) -> "FederatedIdentity":
        email = claims.get(email_claim)
        if not isinstance(email, str) or not email:
            raise ValueError("Email claim not found in ID token")
        # Entra ID omits email_verified for organisational accounts and sends
        # xms_edov ("email domain owner verified") instead. A domain the
        # tenant owner has verified is as authoritative for the address as the
        # standard flag, and the mandatory domain allowlist still applies.
        # A later claim is only a fallback for missing earlier ones: any value
        # the IdP does send, negative or unrecognised, keeps its own verdict.
        deciding = next(
            (name for name in email_verified_claims if claims.get(name) is not None),
            None,
        )
        verdict = claims[deciding] if deciding is not None else None
        if email_claim == "email" and deciding == "email_verified" and verdict is False:
            raise ValueError("Email is not verified by the identity provider")
        subject = claims.get(subject_claim)
        if not isinstance(subject, str) or not subject:
            raise ValueError("ID token is missing its subject")
        try:
            return cls(
                issuer=issuer,
                audience=audience,
                subject_claim=subject_claim,
                subject=subject,
                email=email,
                # The verification claims verify the standard email, not an
                # unrelated address selected by a custom claims mapping.
                email_verified=_is_verified_claim(verdict)
                and claims.get("email") == email,
            )
        except ValueError as exc:
            raise ValueError(
                "Email claim from identity provider is invalid. Contact your administrator."
            ) from exc
