"""Local Eneo password policy and domain failures.

This module is the canonical owner of constraints for passwords stored in the
``users`` table.  Provider-managed passwords (for example Zitadel or an
external identity provider) deliberately do not use this policy.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

LOCAL_PASSWORD_MIN_LENGTH = 12
BCRYPT_MAX_PASSWORD_BYTES = 72


@dataclass(frozen=True)
class LocalPasswordPolicy:
    min_length: int = LOCAL_PASSWORD_MIN_LENGTH
    max_bytes: int = BCRYPT_MAX_PASSWORD_BYTES
    requires_uppercase: bool = False
    requires_lowercase: bool = False
    requires_number: bool = False
    requires_symbol: bool = False


LOCAL_PASSWORD_POLICY = LocalPasswordPolicy()


class PasswordChangeError(Exception):
    """Base class for password-change failures exposed by the API adapter."""

    code: str

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.details = details


class CurrentPasswordIncorrectError(PasswordChangeError):
    code = "current_password_incorrect"


class PasswordReuseError(PasswordChangeError):
    code = "password_reuse"


class PasswordPolicyViolationError(PasswordChangeError):
    code = "password_policy_violation"


class LocalPasswordChangeUnavailableError(PasswordChangeError):
    code = "local_password_change_unavailable"


class PasswordChangeRequiredError(PasswordChangeError):
    """A password session may only change its password until it does so."""

    code = "password_change_required"


PasswordChangeReason = Literal["admin_set", "expired"]


class PasswordLifecyclePolicy(BaseModel):
    """Tenant policy for when a local password must be replaced.

    Stored as ``tenants.password_policy`` (JSONB). Missing keys fall back to
    these defaults, so rows written before a key existed keep working.
    """

    require_change_after_admin_set: bool = Field(
        default=True,
        description=(
            "A password set by an administrator or provisioning is a one-time "
            "password: the account must choose its own at the next password login."
        ),
    )
    max_age_days: Optional[int] = Field(
        default=None,
        ge=1,
        le=3650,
        description=(
            "Days a local password stays valid before the account must choose a "
            "new one at its next password login. Unset disables rotation."
        ),
    )

    model_config = ConfigDict(extra="ignore")

    @classmethod
    def from_tenant(cls, policy: Mapping[str, Any] | None) -> "PasswordLifecyclePolicy":
        return cls.model_validate(dict(policy or {}))


class PasswordLifecyclePolicyUpdate(BaseModel):
    require_change_after_admin_set: Optional[bool] = None
    max_age_days: Optional[int] = Field(default=None, ge=1, le=3650)

    model_config = ConfigDict(extra="forbid")


class PasswordStatusPublic(BaseModel):
    """Where a local password stands against the tenant lifecycle policy."""

    change_required: bool
    reason: Optional[PasswordChangeReason] = None
    changed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


def evaluate_password_status(
    *,
    change_required: bool,
    changed_at: Optional[datetime],
    policy: PasswordLifecyclePolicy,
    now: Optional[datetime] = None,
) -> PasswordStatusPublic:
    """Decide whether a local password must be replaced before normal use.

    An explicit requirement (admin-set password) wins over expiry. A password
    with no recorded change time cannot expire: the migration stamps existing
    rows, so a NULL only occurs for accounts without a local password.
    """

    now = now or datetime.now(timezone.utc)
    expires_at: Optional[datetime] = None
    if policy.max_age_days is not None and changed_at is not None:
        expires_at = changed_at + timedelta(days=policy.max_age_days)

    if change_required:
        return PasswordStatusPublic(
            change_required=True,
            reason="admin_set",
            changed_at=changed_at,
            expires_at=expires_at,
        )
    if expires_at is not None and expires_at <= now:
        return PasswordStatusPublic(
            change_required=True,
            reason="expired",
            changed_at=changed_at,
            expires_at=expires_at,
        )
    return PasswordStatusPublic(
        change_required=False, changed_at=changed_at, expires_at=expires_at
    )


def validate_new_local_password(password: str) -> None:
    """Validate a newly created or changed local password.

    Length is measured in Unicode characters for the minimum and UTF-8 bytes
    for bcrypt's hard maximum. Existing hashes remain valid and are checked by
    the login path; this policy applies only when writing a new credential.
    """

    if len(password) < LOCAL_PASSWORD_POLICY.min_length:
        raise PasswordPolicyViolationError(
            f"Password must contain at least {LOCAL_PASSWORD_POLICY.min_length} characters.",
            details={
                "rule": "min_length",
                "min_length": LOCAL_PASSWORD_POLICY.min_length,
            },
        )

    encoded_length = len(password.encode("utf-8"))
    if encoded_length > LOCAL_PASSWORD_POLICY.max_bytes:
        raise PasswordPolicyViolationError(
            "Password exceeds the maximum size supported by the local password store.",
            details={
                "rule": "max_bytes",
                "max_bytes": LOCAL_PASSWORD_POLICY.max_bytes,
                "actual_bytes": encoded_length,
            },
        )

    for required, pattern, rule in (
        (LOCAL_PASSWORD_POLICY.requires_uppercase, r"[A-Z]", "uppercase_required"),
        (LOCAL_PASSWORD_POLICY.requires_lowercase, r"[a-z]", "lowercase_required"),
        (LOCAL_PASSWORD_POLICY.requires_number, r"[0-9]", "number_required"),
        (LOCAL_PASSWORD_POLICY.requires_symbol, r"[^A-Za-z0-9]", "symbol_required"),
    ):
        if required and re.search(pattern, password) is None:
            raise PasswordPolicyViolationError(
                "Password does not meet the local password policy.",
                details={"rule": rule},
            )
