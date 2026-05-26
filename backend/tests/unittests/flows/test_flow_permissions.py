from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from intric.flows.flow_permissions import (
    ensure_can_manage_flows,
    ensure_can_run_flows,
    ensure_can_use_flow_ai_builder,
    ensure_can_view_flow_trace,
    ensure_can_view_flows,
)
from intric.main.exceptions import UnauthorizedException
from intric.roles.permissions import Permission


def _user(*permissions: Permission):
    return MagicMock(permissions=list(permissions))


def _service_key_user(*permissions: Permission):
    return MagicMock(
        permissions=list(permissions),
        active_api_key=MagicMock(ownership="service"),
    )


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


def test_trace_permission_rejects_view_only_user() -> None:
    with pytest.raises(UnauthorizedException, match="view flow trace"):
        ensure_can_view_flow_trace(_user(Permission.FLOWS_VIEW))


def test_trace_permission_accepts_legacy_flows_alias() -> None:
    ensure_can_view_flow_trace(_user(Permission.FLOWS))


@pytest.mark.parametrize(
    ("checker", "capability"),
    [
        (ensure_can_view_flows, "view"),
        (ensure_can_run_flows, "run"),
        (ensure_can_manage_flows, "manage"),
        (ensure_can_use_flow_ai_builder, "ai_builder"),
        (ensure_can_view_flow_trace, "trace"),
    ],
)
def test_service_key_principals_fail_closed_with_typed_error(
    checker, capability
) -> None:
    with pytest.raises(UnauthorizedException) as exc_info:
        checker(_service_key_user())

    assert exc_info.value.code == "flow_service_key_principal_not_supported"
    context = exc_info.value.context
    assert context is not None
    assert context["auth_layer"] == "service_key_principal"
    assert context["capability"] == capability

    if capability == "view":
        assert context["runtime_endpoint_hint"] == {
            "key": "published_flow_runtime",
            "description": "Use the published runtime projection for service-key Flow clients.",
        }
    else:
        assert "runtime_endpoint_hint" not in context
