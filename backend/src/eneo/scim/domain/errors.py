class ScimUserNotFoundError(Exception):
    pass


class ScimUserConflictError(Exception):
    pass


class ScimGroupNotFoundError(Exception):
    pass


class ScimGroupConflictError(Exception):
    pass


class ScimValidationError(Exception):
    pass


class ScimInvalidFilterError(Exception):
    """RFC 7644 §3.4.2.2: server returns 400 invalidFilter for filter
    expressions that are unparseable or reference unsupported attributes."""

    pass


class ScimHttpError(Exception):
    def __init__(
        self, status_code: int, detail: str, scim_type: str | None = None
    ) -> None:
        self.status_code = status_code
        self.detail = detail
        self.scim_type = scim_type
