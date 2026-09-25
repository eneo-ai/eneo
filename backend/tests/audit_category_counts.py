"""The one place the expected audit category sizes live.

Three tests assert these numbers (two unit modules and one integration
module). Adding an ``ActionType`` means updating this file once, not hunting
for the copies.
"""

EXPECTED_CATEGORY_COUNTS: dict[str, int] = {
    "admin_actions": 70,
    "user_actions": 49,
    "security_events": 12,
    "file_operations": 6,
    "integration_events": 19,
    "system_actions": 3,
    "audit_access": 3,  # Includes AUDIT_SESSION_CREATED
}
