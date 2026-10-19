"""Graph failure classification and stable messages surfaced to people."""

from __future__ import annotations

from typing import Iterator, Optional

import aiohttp

from eneo.integration.infrastructure.auth_service.org_token_provider import (
    CREDENTIALS_INVALID_MESSAGE,
    SharePointCredentialsInvalidError,
    SharePointCredentialsRefusedError,
)
from eneo.main.exceptions import BadRequestException

# A response about an individual item, not a transient Graph/network failure.
ITEM_LEVEL_HTTP_STATUSES = frozenset({403, 404, 410})

NO_SITE_ACCESS_MESSAGE = "Eneo has no access to this site"


def _causes(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def user_facing_sharepoint_error(exc: BaseException) -> Optional[str]:
    """A stable message for failures a person can act on, else None.

    Token-endpoint refusals and Graph 401s both mean the organisation's
    credentials no longer work; a Graph 403 means the credentials work but the
    site is not shared with Eneo. Everything else keeps its original message.
    """
    for cause in _causes(exc):
        if isinstance(cause, SharePointCredentialsInvalidError):
            return CREDENTIALS_INVALID_MESSAGE
        if isinstance(cause, aiohttp.ClientResponseError):
            if cause.status == 403:
                return NO_SITE_ACCESS_MESSAGE
            if cause.status == 401:
                return CREDENTIALS_INVALID_MESSAGE
    return None


def user_facing_sharepoint_failure(exc: BaseException) -> BadRequestException | None:
    """``user_facing_sharepoint_error`` as the 400 to raise; refused
    credentials carry the same ``code`` as an import or sync reports."""
    message = user_facing_sharepoint_error(exc)
    if message is None:
        return None
    if message == CREDENTIALS_INVALID_MESSAGE:
        return SharePointCredentialsRefusedError()
    return BadRequestException(message)
