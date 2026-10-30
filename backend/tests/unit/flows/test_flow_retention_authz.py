"""The one retention authorization owner: a permission per duty, people only."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from eneo.authentication.auth_models import ApiKeyOwnership
from eneo.flows.application.flow_retention_authz import (
    require_retention_holds,
    require_retention_manage,
    require_retention_view,
)
from eneo.main.exceptions import UnauthorizedException
from eneo.roles.permissions import Permission

MANAGE = Permission.RETENTION_MANAGE
HOLDS = Permission.RETENTION_HOLDS
CHECKS = {
    "manage": require_retention_manage,
    "holds": require_retention_holds,
    "view": require_retention_view,
}


def _person(*permissions: Permission) -> SimpleNamespace:
    return SimpleNamespace(permissions=list(permissions), active_api_key=None)


def _key(ownership: ApiKeyOwnership, *permissions: Permission) -> SimpleNamespace:
    return SimpleNamespace(
        permissions=list(permissions),
        active_api_key=SimpleNamespace(ownership=ownership),
    )


@pytest.mark.parametrize(
    ("permissions", "allowed"),
    [
        ((MANAGE,), {"manage", "view"}),
        ((HOLDS,), {"holds", "view"}),
        ((MANAGE, HOLDS), {"manage", "holds", "view"}),
        ((Permission.ADMIN,), set()),
        ((Permission.FLOWS_MANAGE, Permission.EDITOR), set()),
        ((), set()),
    ],
)
def test_each_duty_needs_its_own_permission(
    permissions: tuple[Permission, ...], allowed: set[str]
) -> None:
    user = _person(*permissions)
    for name, check in CHECKS.items():
        if name in allowed:
            check(user)  # type: ignore[arg-type]
            continue
        with pytest.raises(UnauthorizedException) as refused:
            check(user)  # type: ignore[arg-type]
        assert refused.value.code == "retention_permission_required"


@pytest.mark.parametrize("ownership", list(ApiKeyOwnership))
def test_an_api_key_is_refused_whatever_its_permissions(
    ownership: ApiKeyOwnership,
) -> None:
    caller = _key(ownership, MANAGE, HOLDS, Permission.ADMIN)
    for check in CHECKS.values():
        with pytest.raises(UnauthorizedException) as refused:
            check(caller)  # type: ignore[arg-type]
        assert refused.value.code == "retention_person_required"
