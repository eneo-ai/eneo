"""Who may read what users uploaded to conversations.

A user-owned API key acts as its owner, but its ``files`` resource grant is
a ceiling of its own: without ``files: read`` the key reads neither the
uploads a request names nor those an earlier turn attached. The assistant's
configured knowledge and the files an answer generated are conversation
data, authorized through their own owners.
"""

from eneo.authentication.api_key_resolver import (
    ApiKeyValidationError,
    check_resource_permission,
)
from eneo.main.exceptions import UnauthorizedException
from eneo.users.user import UserInDB


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


def require_file_read_permission(user: UserInDB) -> None:
    """Refuse a request that names files the principal may not read."""
    denial = user_upload_read_denial(user)
    if denial is not None:
        raise UnauthorizedException(
            denial.message,
            code=denial.code,
            context=dict(denial.context) if denial.context is not None else None,
        ) from denial
