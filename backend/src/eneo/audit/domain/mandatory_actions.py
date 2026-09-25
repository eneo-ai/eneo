"""Audit actions a tenant can never turn off.

These record access and changes a tenant administrator makes without space
membership, changes to user groups (a group's role in a space reaches its
content), and publishing a widget to the open web. The same administrators
can change the audit configuration, so letting them silence these would
defeat the control. They bypass the global switch, category toggles and
action overrides. ``AuditService`` never queues them: ``log_async`` writes
them like ``log_required``, on the caller's session, so an entry commits or
rolls back with the change it records. Retention never purges them before
MANDATORY_AUDIT_MIN_RETENTION_DAYS, whatever the tenant's retention.

ActionType is a ``str`` enum, so membership also works for raw values.
"""

from eneo.audit.domain.action_types import ActionType

MANDATORY_AUDIT_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.SPACE_OVERSIGHT_JOINED,
        ActionType.SPACE_OVERSIGHT_LEFT,
        ActionType.SPACE_OVERSIGHT_MEMBER_ADDED,
        ActionType.SPACE_OVERSIGHT_MEMBER_ROLE_CHANGED,
        ActionType.SPACE_OVERSIGHT_MEMBER_REMOVED,
        ActionType.USER_GROUP_MEMBER_ADDED,
        ActionType.USER_GROUP_MEMBER_REMOVED,
        ActionType.WIDGET_ACTIVATION_REQUEST_DECLINED,
        ActionType.WIDGET_ACTIVATED,
        ActionType.WIDGET_PAUSED,
        ActionType.WIDGET_ARCHIVED,
    }
)

MANDATORY_AUDIT_MIN_RETENTION_DAYS = 365
