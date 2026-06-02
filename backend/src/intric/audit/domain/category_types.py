from enum import Enum


class CategoryType(str, Enum):
    """Audit categories that every action type rolls up into.

    Single source of truth for the category vocabulary: CATEGORY_MAPPINGS,
    the config schemas, and the config service all derive from this enum, and
    it surfaces in the OpenAPI schema so the frontend can translate categories
    by key (no display text crosses the API).
    """

    ADMIN_ACTIONS = "admin_actions"
    USER_ACTIONS = "user_actions"
    SECURITY_EVENTS = "security_events"
    FILE_OPERATIONS = "file_operations"
    INTEGRATION_EVENTS = "integration_events"
    SYSTEM_ACTIONS = "system_actions"
    AUDIT_ACCESS = "audit_access"
