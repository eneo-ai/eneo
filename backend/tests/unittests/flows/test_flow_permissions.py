from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from intric.flows.flow_permissions import (
    ensure_can_manage_flows,
    ensure_can_use_flow_ai_builder,
    ensure_can_view_flows,
)
from intric.main.exceptions import UnauthorizedException
from intric.roles.permissions import Permission


def _user(*permissions: Permission):
    return MagicMock(permissions=list(permissions))


def test_view_permission_accepts_legacy_flows_alias() -> None:
    ensure_can_view_flows(_user(Permission.FLOWS))


def test_manage_permission_rejects_view_only_user() -> None:
    with pytest.raises(UnauthorizedException, match="manage flows"):
        ensure_can_manage_flows(_user(Permission.FLOWS_VIEW))


def test_ai_builder_requires_manage_and_builder_permission() -> None:
    with pytest.raises(UnauthorizedException, match="use Flow AI Builder"):
        ensure_can_use_flow_ai_builder(_user(Permission.FLOWS_MANAGE))


def test_ai_builder_accepts_legacy_flows_alias() -> None:
    ensure_can_use_flow_ai_builder(_user(Permission.FLOWS))
