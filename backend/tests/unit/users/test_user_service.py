"""Service-key principals: the permission set synthesized for a service key.

Service keys resolve to a synthetic user with no ``users`` row, so they may
only hold permissions whose use never inserts a row keyed on ``user_id``.
"""

from unittest.mock import MagicMock

from eneo.roles.permissions import Permission
from eneo.users.user_service import _synthesize_service_key_permissions


def _key(scope_type: str = "space", permission: str = "write") -> MagicMock:
    key = MagicMock()
    key.scope_type = scope_type
    key.permission = permission
    return key


class TestServiceKeyPermissions:
    def test_web_search_is_granted(self):
        assert Permission.WEB_SEARCH in _synthesize_service_key_permissions(_key())

    def test_image_generation_is_withheld(self):
        # A generated image is persisted as a file bound to user_id; the
        # synthetic service user cannot own one, so the capability is off.
        permissions = _synthesize_service_key_permissions(_key())
        assert Permission.IMAGE_GENERATION not in permissions

    def test_tenant_admin_key_adds_admin_only(self):
        base = _synthesize_service_key_permissions(_key())
        admin = _synthesize_service_key_permissions(_key("tenant", "admin"))
        assert admin - base == {Permission.ADMIN}
