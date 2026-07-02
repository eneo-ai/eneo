from __future__ import annotations

import pytest

from eneo.authentication.api_key_resolver import (
    ApiKeyValidationError,
    check_resource_permission,
)
from eneo.authentication.auth_models import ApiKeyPermission
from tests.unit.api_key_test_utils import make_api_key


def test_flows_resource_permission_uses_basic_permission_when_no_fine_grained_permissions() -> (
    None
):
    key = make_api_key(
        default_permission=ApiKeyPermission.ADMIN,
        resource_permissions=None,
    )

    check_resource_permission(key, "flows", "read")
    check_resource_permission(key, "flows", "write")


def test_flows_resource_permission_requires_explicit_flow_grant_when_fine_grained() -> (
    None
):
    key = make_api_key(
        default_permission=ApiKeyPermission.ADMIN,
        resource_permissions={"flow_evidence": "read"},
    )

    with pytest.raises(ApiKeyValidationError) as exc_info:
        check_resource_permission(key, "flows", "read")

    assert exc_info.value.code == "insufficient_resource_permission"


def test_flows_resource_permission_allows_explicit_flow_grant() -> None:
    key = make_api_key(
        default_permission=ApiKeyPermission.READ,
        resource_permissions={"flows": "write", "flow_evidence": "read"},
    )

    check_resource_permission(key, "flows", "read")
    check_resource_permission(key, "flows", "write")


def test_flows_resource_permission_basic_fallback_still_denies_above_basic_permission() -> (
    None
):
    key = make_api_key(
        default_permission=ApiKeyPermission.READ,
        resource_permissions=None,
    )

    with pytest.raises(ApiKeyValidationError) as exc_info:
        check_resource_permission(key, "flows", "write")

    assert exc_info.value.code == "insufficient_resource_permission"
