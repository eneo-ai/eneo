"""Local Eneo password policy and domain failures.

This module is the canonical owner of constraints for passwords stored in the
``users`` table.  Provider-managed passwords (for example Zitadel or an
external identity provider) deliberately do not use this policy.
"""

from dataclasses import dataclass

LOCAL_PASSWORD_MIN_LENGTH = 15
BCRYPT_MAX_PASSWORD_BYTES = 72


@dataclass(frozen=True)
class LocalPasswordPolicy:
    min_length: int = LOCAL_PASSWORD_MIN_LENGTH
    max_bytes: int = BCRYPT_MAX_PASSWORD_BYTES


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
