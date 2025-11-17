"""Category mappings for audit log action types."""

from intric.audit.domain.action_types import ActionType


# Category descriptions for UI display
CATEGORY_DESCRIPTIONS = {
    'admin_actions': 'User management, role changes, API keys, tenant settings',
    'user_actions': 'Assistant, space, app operations, templates, model configs',
    'security_events': 'Security classification lifecycle events',
    'file_operations': 'File uploads and deletions',
    'integration_events': 'Integration connections, knowledge sources, website crawling',
    'system_actions': 'Retention policies, encryption, maintenance',
    'audit_access': 'Viewing and exporting audit logs',
}


# Map all ActionType constants to categories (using string values as keys)
CATEGORY_MAPPINGS = {
    # Admin Actions (13 actions)
    ActionType.USER_CREATED.value: 'admin_actions',
    ActionType.USER_DELETED.value: 'admin_actions',
    ActionType.USER_UPDATED.value: 'admin_actions',
    ActionType.ROLE_CREATED.value: 'admin_actions',
    ActionType.ROLE_MODIFIED.value: 'admin_actions',
    ActionType.ROLE_DELETED.value: 'admin_actions',
    ActionType.PERMISSION_CHANGED.value: 'admin_actions',
    ActionType.API_KEY_GENERATED.value: 'admin_actions',
    ActionType.TENANT_SETTINGS_UPDATED.value: 'admin_actions',
    ActionType.CREDENTIALS_UPDATED.value: 'admin_actions',
    ActionType.FEDERATION_UPDATED.value: 'admin_actions',
    ActionType.MODULE_ADDED.value: 'admin_actions',
    ActionType.MODULE_ADDED_TO_TENANT.value: 'admin_actions',

    # User Actions (28 actions)
    ActionType.ASSISTANT_CREATED.value: 'user_actions',
    ActionType.ASSISTANT_UPDATED.value: 'user_actions',
    ActionType.ASSISTANT_DELETED.value: 'user_actions',
    ActionType.ASSISTANT_TRANSFERRED.value: 'user_actions',
    ActionType.ASSISTANT_PUBLISHED.value: 'user_actions',
    ActionType.SPACE_CREATED.value: 'user_actions',
    ActionType.SPACE_UPDATED.value: 'user_actions',
    ActionType.SPACE_DELETED.value: 'user_actions',
    ActionType.SPACE_MEMBER_ADDED.value: 'user_actions',
    ActionType.SPACE_MEMBER_REMOVED.value: 'user_actions',
    ActionType.APP_CREATED.value: 'user_actions',
    ActionType.APP_DELETED.value: 'user_actions',
    ActionType.APP_UPDATED.value: 'user_actions',
    ActionType.APP_EXECUTED.value: 'user_actions',
    ActionType.APP_PUBLISHED.value: 'user_actions',
    ActionType.APP_RUN_DELETED.value: 'user_actions',
    ActionType.COLLECTION_CREATED.value: 'user_actions',
    ActionType.COLLECTION_UPDATED.value: 'user_actions',
    ActionType.COLLECTION_DELETED.value: 'user_actions',
    ActionType.TEMPLATE_CREATED.value: 'user_actions',
    ActionType.TEMPLATE_UPDATED.value: 'user_actions',
    ActionType.TEMPLATE_DELETED.value: 'user_actions',
    ActionType.GROUP_CHAT_CREATED.value: 'user_actions',
    ActionType.SESSION_STARTED.value: 'user_actions',
    ActionType.SESSION_ENDED.value: 'user_actions',
    ActionType.COMPLETION_MODEL_UPDATED.value: 'user_actions',
    ActionType.EMBEDDING_MODEL_UPDATED.value: 'user_actions',
    ActionType.TRANSCRIPTION_MODEL_UPDATED.value: 'user_actions',

    # Security Events (6 actions)
    ActionType.SECURITY_CLASSIFICATION_CREATED.value: 'security_events',
    ActionType.SECURITY_CLASSIFICATION_UPDATED.value: 'security_events',
    ActionType.SECURITY_CLASSIFICATION_DELETED.value: 'security_events',
    ActionType.SECURITY_CLASSIFICATION_LEVELS_UPDATED.value: 'security_events',
    ActionType.SECURITY_CLASSIFICATION_ENABLED.value: 'security_events',
    ActionType.SECURITY_CLASSIFICATION_DISABLED.value: 'security_events',

    # File Operations (2 actions)
    ActionType.FILE_UPLOADED.value: 'file_operations',
    ActionType.FILE_DELETED.value: 'file_operations',

    # Integration Events (11 actions)
    ActionType.INTEGRATION_ADDED.value: 'integration_events',
    ActionType.INTEGRATION_REMOVED.value: 'integration_events',
    ActionType.INTEGRATION_CONNECTED.value: 'integration_events',
    ActionType.INTEGRATION_DISCONNECTED.value: 'integration_events',
    ActionType.INTEGRATION_KNOWLEDGE_CREATED.value: 'integration_events',
    ActionType.INTEGRATION_KNOWLEDGE_DELETED.value: 'integration_events',
    ActionType.WEBSITE_CREATED.value: 'integration_events',
    ActionType.WEBSITE_UPDATED.value: 'integration_events',
    ActionType.WEBSITE_DELETED.value: 'integration_events',
    ActionType.WEBSITE_CRAWLED.value: 'integration_events',
    ActionType.WEBSITE_TRANSFERRED.value: 'integration_events',

    # System Actions (3 actions)
    ActionType.RETENTION_POLICY_APPLIED.value: 'system_actions',
    ActionType.ENCRYPTION_KEY_ROTATED.value: 'system_actions',
    ActionType.SYSTEM_MAINTENANCE.value: 'system_actions',

    # Audit Access (2 actions)
    ActionType.AUDIT_LOG_VIEWED.value: 'audit_access',
    ActionType.AUDIT_LOG_EXPORTED.value: 'audit_access',
}


def get_category_for_action(action: str) -> str:
    """
    Get category for a given action type.

    Args:
        action: ActionType constant (string value)

    Returns:
        Category name ('admin_actions', 'user_actions', etc.)
        Defaults to 'user_actions' if action not found.
    """
    return CATEGORY_MAPPINGS.get(action, 'user_actions')
