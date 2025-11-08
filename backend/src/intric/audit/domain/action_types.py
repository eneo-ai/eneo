from enum import Enum


class ActionType(str, Enum):
    """Standardized vocabulary of auditable actions"""

    # Admin Actions (Priority 1)
    USER_CREATED = "user_created"
    USER_DELETED = "user_deleted"
    USER_UPDATED = "user_updated"
    ROLE_MODIFIED = "role_modified"
    PERMISSION_CHANGED = "permission_changed"
    TENANT_SETTINGS_UPDATED = "tenant_settings_updated"
    CREDENTIALS_UPDATED = "credentials_updated"
    FEDERATION_UPDATED = "federation_updated"

    # User Actions (Priority 2)
    ASSISTANT_CREATED = "assistant_created"
    ASSISTANT_DELETED = "assistant_deleted"
    ASSISTANT_UPDATED = "assistant_updated"
    SPACE_CREATED = "space_created"
    SPACE_UPDATED = "space_updated"
    SPACE_MEMBER_ADDED = "space_member_added"
    SPACE_MEMBER_REMOVED = "space_member_removed"
    APP_CREATED = "app_created"
    APP_DELETED = "app_deleted"
    APP_UPDATED = "app_updated"
    APP_EXECUTED = "app_executed"
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"
    FILE_UPLOADED = "file_uploaded"
    FILE_DELETED = "file_deleted"
    WEBSITE_CRAWLED = "website_crawled"

    # System Actions
    RETENTION_POLICY_APPLIED = "retention_policy_applied"
    ENCRYPTION_KEY_ROTATED = "encryption_key_rotated"
    SYSTEM_MAINTENANCE = "system_maintenance"
