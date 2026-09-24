"""Audit actions a tenant can never turn off.

These record access and changes a tenant administrator makes without space
membership, and publishing a widget to the open web. The same administrators
can change the audit configuration, so letting them silence these would
defeat the control. They bypass the global switch, category toggles and
action overrides. Request handlers write them with
``AuditService.log_required`` in the transaction that makes the change.

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
        ActionType.WIDGET_ACTIVATION_REQUEST_DECLINED,
        ActionType.WIDGET_ACTIVATED,
        ActionType.WIDGET_PAUSED,
        ActionType.WIDGET_ARCHIVED,
    }
)
