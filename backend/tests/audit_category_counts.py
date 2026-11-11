"""The one place the expected audit category sizes live.

Three tests assert these numbers (two unit modules and one integration
module). Adding an ``ActionType`` means updating this file once, not hunting
for the copies.
"""

EXPECTED_CATEGORY_COUNTS: dict[str, int] = {
    "admin_actions": 75,
    "user_actions": 93,
    "security_events": 17,
    "file_operations": 8,
    "integration_events": 24,
    "system_actions": 8,
    "audit_access": 6,  # Includes AUDIT_SESSION_CREATED
}
