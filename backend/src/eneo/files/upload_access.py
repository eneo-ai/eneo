"""Who may read what users uploaded to conversations.

A user-owned API key acts as its owner, but its ``files`` resource grant is
a ceiling of its own: without ``files: read`` the key reads neither the
uploads a request names nor those an earlier turn attached. The assistant's
configured knowledge and the files an answer generated are conversation
data, authorized through their own owners.
"""

from typing import TYPE_CHECKING

from eneo.authentication.api_key_audit import log_api_key_auth_failed
from eneo.authentication.api_key_resolver import (
    PUBLIC_DENIAL_CONTEXT_KEYS,
    ApiKeyValidationError,
    check_resource_permission,
)
from eneo.main.exceptions import UnauthorizedException
from eneo.users.user import UserInDB

if TYPE_CHECKING:
    from eneo.audit.application.audit_service import AuditService


def user_upload_read_denial(user: UserInDB) -> ApiKeyValidationError | None:
    """Why this principal may not read user uploads, or None when it may."""
    # getattr: fixtures hand in bare user records without the request-scoped
    # field, as ``is_service_api_key`` already tolerates.
    key = getattr(user, "active_api_key", None)
    if key is None:
        return None
    try:
        check_resource_permission(key, "files", "read")
    except ApiKeyValidationError as denial:
        return denial
    return None


def may_read_user_uploads(user: UserInDB) -> bool:
    """False only for an API key without the ``files`` read grant."""
    return user_upload_read_denial(user) is None


async def require_file_read_permission(
    user: UserInDB, audit_service: "AuditService | None"
) -> None:
    """Refuse a request that names files the principal may not read.

    Recorded and answered like the same denial at a route: an audit entry for
    the failed key, and only the public context fields in the response.
    """
    key = getattr(user, "active_api_key", None)
    denial = user_upload_read_denial(user)
    if key is None or denial is None:
        return
    await log_api_key_auth_failed(audit_service, user, key, denial)
    raise UnauthorizedException(
        denial.message,
        code=denial.code,
        context={
            key: value
            for key, value in (denial.context or {}).items()
            if key in PUBLIC_DENIAL_CONTEXT_KEYS
        }
        or None,
    ) from denial
