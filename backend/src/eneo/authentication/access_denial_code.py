from enum import StrEnum, unique


@unique
class AccessDenialCode(StrEnum):
    """Codes with which a 403 names the access layer that refused the caller.

    Flows and flow packages raise all four through these members. Other parts
    of the platform raise insufficient_scope and forbidden_action as string
    literals, and answer some of the same situations with other codes.
    """

    INSUFFICIENT_SCOPE = "insufficient_scope"
    INSUFFICIENT_SPACE_PERMISSION = "insufficient_space_permission"
    INSUFFICIENT_TENANT_PERMISSION = "insufficient_tenant_permission"
    FORBIDDEN_ACTION = "forbidden_action"
