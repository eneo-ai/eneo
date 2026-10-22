"""When a local Eneo password must be replaced, and which sessions that blocks.

This module is the single owner of the lifecycle decision. The tenant policy
(``tenants.password_policy``) and the account's stamps
(``users.password_changed_at``, ``users.password_change_required``) are
written by ``UserService`` and read only here. Two callers consume the
decision and must never disagree: the admission gate in
``eneo.authentication.endpoint_access`` and the ``password_status`` field of
``GET /users/me/``.

Only a session that signed in with the local password is ever blocked. A
federated (OIDC/Zitadel) session, a module or MCP token and an API key carry
no password claim, so an account that also keeps an old local hash is not
locked out of the sign-in method it actually used.
"""

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from eneo.users.user import UserInDB

#: Value of the session claim ``auth_method`` minted by the password login.
PASSWORD_AUTH_METHOD = "password"

PasswordChangeReason = Literal["admin_set", "expired"]

_MAX_AGE_DAYS_LIMIT = 3650


class PasswordLifecyclePolicy(BaseModel):
    """Tenant policy for when a local password must be replaced.

    Stored as ``tenants.password_policy`` (JSONB). Missing keys fall back to
    these defaults, so rows written before a key existed keep working.

    A password someone else set is always one-time and is not a tenant
    choice; only the sysadmin API and the deployment seed may opt a single
    account out (``password_change_required``).
    """

    max_age_days: Optional[int] = Field(
        default=None,
        ge=1,
        le=_MAX_AGE_DAYS_LIMIT,
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
    # PATCH uses exclude_unset=True: an omitted key is left as it is.
    max_age_days: Optional[int] = Field(default=None, ge=1, le=_MAX_AGE_DAYS_LIMIT)

    model_config = ConfigDict(extra="forbid")


class PasswordStatusPublic(BaseModel):
    """Where a local password stands against the tenant lifecycle policy.

    ``change_required`` is true only when the current session is blocked
    until the password is replaced; the dates are reported regardless.
    """

    change_required: bool
    reason: Optional[PasswordChangeReason] = None
    changed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class PasswordChangeRequiredError(Exception):
    """The session may only replace its password until it has done so."""

    code = "password_change_required"

    def __init__(self, reason: PasswordChangeReason) -> None:
        super().__init__("Choose a new password before continuing.")
        self.reason = reason
        self.details: dict[str, object] = {"reason": reason}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


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

    now = _aware(now) if now is not None else datetime.now(timezone.utc)
    changed_at = _aware(changed_at) if changed_at is not None else None
    expires_at: Optional[datetime] = None
    if policy.max_age_days is not None and changed_at is not None:
        expires_at = changed_at + timedelta(days=policy.max_age_days)

    if change_required:
        reason: Optional[PasswordChangeReason] = "admin_set"
    elif expires_at is not None and expires_at <= now:
        reason = "expired"
    else:
        reason = None
    return PasswordStatusPublic(
        change_required=reason is not None,
        reason=reason,
        changed_at=changed_at,
        expires_at=expires_at,
    )


def password_status_for(
    user: "UserInDB", *, now: Optional[datetime] = None
) -> Optional[PasswordStatusPublic]:
    """The account's password status as it applies to the current session.

    None for accounts without a local password. For a session that did not
    sign in with the password, the dates are kept but nothing is required.
    """

    if user.password is None:
        return None
    status = evaluate_password_status(
        change_required=user.password_change_required,
        changed_at=user.password_changed_at,
        policy=PasswordLifecyclePolicy.from_tenant(user.tenant.password_policy),
        now=now,
    )
    if user.session_auth_method != PASSWORD_AUTH_METHOD:
        return status.model_copy(update={"change_required": False, "reason": None})
    return status


def enforce_password_change(user: "UserInDB") -> None:
    """Raise when this session must replace its password before continuing."""

    status = password_status_for(user)
    if status is not None and status.change_required and status.reason is not None:
        raise PasswordChangeRequiredError(status.reason)
