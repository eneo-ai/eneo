from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from eneo.flows.flow_access_policy import (
    FlowApiAction,
    require_flow_action,
    user_can_perform_flow_action,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.exceptions import UnauthorizedException
from eneo.roles.permissions import Permission


def _user(*permissions: Permission):
    return MagicMock(id=uuid4(), permissions=list(permissions))


def _service_key_user(*permissions: Permission):
    return MagicMock(
        id=uuid4(),
        permissions=list(permissions),
        active_api_key=SimpleNamespace(
            id=uuid4(),
            ownership="service",
            service_principal_id=uuid4(),
        ),
    )


@pytest.mark.parametrize(
    ("action", "permissions"),
    [
        (FlowApiAction.VIEW, [Permission.FLOWS_VIEW]),
        (FlowApiAction.RUN, [Permission.FLOWS_RUN]),
        (FlowApiAction.EDIT, [Permission.FLOWS_MANAGE]),
        (FlowApiAction.REVIEW, [Permission.FLOWS_MANAGE]),
        (FlowApiAction.RESUME, [Permission.FLOWS_MANAGE]),
        (
            FlowApiAction.TRACE_VIEW,
            [Permission.FLOWS_VIEW, Permission.FLOWS_TRACE],
        ),
    ],
)
def test_policy_accepts_explicit_permissions_for_shipped_actions(
    action: FlowApiAction, permissions: list[Permission]
) -> None:
    assert user_can_perform_flow_action(_user(*permissions), action) is True


@pytest.mark.parametrize(
    "action",
    [
        FlowApiAction.AUDIT_VIEW,
    ],
)
@pytest.mark.parametrize(
    "permissions",
    [
        [Permission.FLOWS],
        [Permission.FLOWS_MANAGE],
        [Permission.FLOWS_RUN],
    ],
)
def test_coarse_permissions_do_not_grant_unimplemented_actions(
    action: FlowApiAction, permissions: list[Permission]
) -> None:
    assert user_can_perform_flow_action(_user(*permissions), action) is False


@pytest.mark.parametrize(
    "action",
    [
        FlowApiAction.VIEW,
        FlowApiAction.RUN,
        FlowApiAction.EDIT,
        FlowApiAction.REVIEW,
        FlowApiAction.RESUME,
        FlowApiAction.TRACE_VIEW,
    ],
)
def test_coarse_flows_alias_keeps_current_shipped_grants(
    action: FlowApiAction,
) -> None:
    assert user_can_perform_flow_action(_user(Permission.FLOWS), action) is True


def test_edit_requires_manage_permission_not_view_only() -> None:
    with pytest.raises(UnauthorizedException, match="manage flows"):
        require_flow_action(_user(Permission.FLOWS_VIEW), FlowApiAction.EDIT)


@pytest.mark.parametrize(
    ("action", "capability"),
    [
        (FlowApiAction.REVIEW, "review"),
        (FlowApiAction.RESUME, "resume"),
    ],
)
def test_review_mutations_require_explicit_service_key_opt_in(
    action: FlowApiAction,
    capability: str,
) -> None:
    service_key_user = _service_key_user(Permission.FLOWS_MANAGE)

    with pytest.raises(UnauthorizedException) as exc_info:
        require_flow_action(service_key_user, action)

    assert (
        exc_info.value.code
        == FlowApiErrorCode.SERVICE_KEY_PRINCIPAL_NOT_SUPPORTED.value
    )
    assert exc_info.value.context == {
        "auth_layer": "service_key_principal",
        "capability": capability,
    }

    require_flow_action(
        service_key_user,
        action,
        allow_service_key_principals=True,
    )


def test_trace_requires_view_and_trace_permissions() -> None:
    user = _user(Permission.FLOWS_TRACE)

    with pytest.raises(UnauthorizedException, match="view flow trace"):
        require_flow_action(user, FlowApiAction.TRACE_VIEW)


def test_service_key_principals_fail_closed_unless_route_explicitly_allows() -> None:
    service_key_user = _service_key_user(Permission.FLOWS)

    with pytest.raises(UnauthorizedException) as exc_info:
        require_flow_action(service_key_user, FlowApiAction.VIEW)

    assert (
        exc_info.value.code
        == FlowApiErrorCode.SERVICE_KEY_PRINCIPAL_NOT_SUPPORTED.value
    )
    context = exc_info.value.context
    assert context is not None
    assert context["auth_layer"] == "service_key_principal"
    assert context["capability"] == "view"
    hint = context["runtime_endpoint_hint"]
    assert isinstance(hint, dict)
    assert hint["key"] == "published_flow_runtime"
    assert "published runtime" in str(hint["description"])
    assert len(str(hint["description"])) <= 120
    assert "endpoint_template" not in hint

    require_flow_action(
        service_key_user,
        FlowApiAction.VIEW,
        allow_service_key_principals=True,
    )


@pytest.mark.parametrize(
    ("action", "capability"),
    [
        (FlowApiAction.EDIT, "manage"),
        (FlowApiAction.RUN, "run"),
        (FlowApiAction.TRACE_VIEW, "trace"),
    ],
)
def test_non_view_service_key_denials_do_not_get_runtime_endpoint_hint(
    action: FlowApiAction,
    capability: str,
) -> None:
    service_key_user = _service_key_user(Permission.FLOWS)

    with pytest.raises(UnauthorizedException) as exc_info:
        require_flow_action(service_key_user, action)

    assert (
        exc_info.value.code
        == FlowApiErrorCode.SERVICE_KEY_PRINCIPAL_NOT_SUPPORTED.value
    )
    assert exc_info.value.context == {
        "auth_layer": "service_key_principal",
        "capability": capability,
    }


def test_flow_permission_mapping_has_one_source_owner() -> None:
    flow_root = Path(__file__).parents[3] / "src" / "eneo" / "flows"
    offenders: list[str] = []
    for path in flow_root.rglob("*.py"):
        if path.name == "flow_access_policy.py":
            continue
        text = path.read_text()
        if "has_permission(" in text and "Permission.FLOWS" in text:
            offenders.append(str(path.relative_to(flow_root)))

    assert offenders == []


def test_service_key_ownership_decode_has_one_source_owner() -> None:
    flow_root = Path(__file__).parents[3] / "src" / "eneo" / "flows"
    offenders: list[str] = []
    for path in flow_root.rglob("*.py"):
        if path.name == "principal.py":
            continue
        text = path.read_text()
        if 'getattr(key, "ownership", "user")' in text or "def is_service_key" in text:
            offenders.append(str(path.relative_to(flow_root)))

    assert offenders == []


def test_flow_routers_do_not_read_raw_api_key_scope_state() -> None:
    flow_root = Path(__file__).parents[3] / "src" / "eneo" / "flows"
    forbidden = (
        "api_key_scope_type",
        "api_key_scope_id",
        "scope_enforcement_enabled",
    )
    offenders: list[str] = []
    for path in flow_root.rglob("*.py"):
        text = path.read_text()
        if any(token in text for token in forbidden):
            offenders.append(str(path.relative_to(flow_root)))

    assert offenders == []


def test_flow_run_user_id_is_not_used_as_a_canonical_owner_path() -> None:
    src_root = Path(__file__).parents[3] / "src" / "eneo"
    searched_roots = [src_root / "flows", src_root / "files"]
    legacy_owner_patterns = [
        re.compile(pattern, re.MULTILINE)
        for pattern in (
            r"\bFlowRuns\.user_id\b",
            r"\bflow_runs(?:\.c)?\.user_id\b",
            r"\bFiles\.user_id\b",
            r"\bfiles(?:\.c)?\.user_id\b",
            r"\brun\.user_id\b",
            r"\bget_list_by_id_and_user\b",
            r"\bdelete_by_owner\(",
            r"\blegacy_user_id\b",
            r'\{"user_id": deps\.user_id\}',
        )
    ]
    offenders: list[str] = []
    for root in searched_roots:
        for path in root.rglob("*.py"):
            text = path.read_text()
            if any(pattern.search(text) for pattern in legacy_owner_patterns):
                offenders.append(str(path.relative_to(src_root)))

    assert offenders == []
