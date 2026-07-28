from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.authentication.auth_models import (
    ApiKeyHashVersion,
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
    ApiKeyV2InDB,
    ResourcePermissionLevel,
    ResourcePermissions,
)
from eneo.authentication.principal_types import PrincipalType
from eneo.flows.application.flow_run_access_policy import (
    FlowRunAccessKind,
    FlowRunAccessPolicy,
)
from eneo.flows.domain.flow import FlowRun, FlowRunStatus
from eneo.flows.domain.flow_run_exceptions import FlowRunNotFoundError
from eneo.flows.flow_evidence_policy import (
    FlowEvidenceAccessContext,
    flow_metadata_marks_sensitive,
)
from eneo.main.exceptions import NotFoundException, UnauthorizedException
from eneo.roles.permissions import Permission


def _run(user, flow_id) -> FlowRun:
    now = datetime.now(timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=flow_id,
        flow_version=1,
        principal_type=PrincipalType.USER.value,
        principal_user_id=user.id,
        tenant_id=user.tenant_id,
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )


def _service_key_user(
    user,
    *,
    resource_permissions: ResourcePermissions | None = None,
):
    service_key = ApiKeyV2InDB(
        id=uuid4(),
        ownership=ApiKeyOwnership.SERVICE,
        owner_user_id=None,
        key_prefix=ApiKeyType.SK.value,
        key_suffix="test",
        name="Flow service key",
        description=None,
        key_type=ApiKeyType.SK,
        permission=ApiKeyPermission.WRITE,
        scope_type=ApiKeyScopeType.TENANT,
        scope_id=None,
        allowed_origins=None,
        allowed_ips=None,
        resource_permissions=resource_permissions,
        state=ApiKeyState.ACTIVE,
        expires_at=None,
        last_used_at=None,
        revoked_at=None,
        revoked_reason_code=None,
        revoked_reason_text=None,
        suspended_at=None,
        suspended_reason_code=None,
        suspended_reason_text=None,
        rotation_grace_until=None,
        rate_limit=None,
        created_at=None,
        updated_at=None,
        rotated_from_key_id=None,
        created_by_user_id=None,
        owner_user=None,
        created_by_user=None,
        search_match_reasons=None,
        tenant_id=user.tenant_id,
        service_principal_id=uuid4(),
        created_by_key_id=None,
        delegation_depth=0,
        key_hash="hash",
        hash_version=ApiKeyHashVersion.HMAC_SHA256,
    )
    return user.model_copy(
        update={
            "active_api_key": service_key,
        }
    )


def _policy(user, *, flow_run_repo: AsyncMock) -> FlowRunAccessPolicy:
    return FlowRunAccessPolicy(
        user=user,
        flow_repo=AsyncMock(),
        flow_run_repo=flow_run_repo,
    )


def _policy_with_space(
    user,
    *,
    flow_repo: AsyncMock,
    flow_run_repo: AsyncMock,
    role: str,
    security_level: int = 0,
) -> FlowRunAccessPolicy:
    space = SimpleNamespace(
        id=uuid4(),
        security_classification=SimpleNamespace(security_level=security_level),
    )
    flow = SimpleNamespace(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=space.id,
        metadata_json=None,
    )
    space_service = AsyncMock()
    actor_manager = MagicMock()
    actor_manager.get_space_actor_from_space.return_value = SimpleNamespace(
        get_current_role=lambda: role
    )
    flow_repo.get.return_value = flow
    space_service.get_space.return_value = space
    return FlowRunAccessPolicy(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        space_service=space_service,
        actor_manager=actor_manager,
    )


@pytest.mark.asyncio
async def test_load_run_allows_owner_content_access(user):
    flow_id = uuid4()
    run = _run(user, flow_id)
    flow_run_repo = AsyncMock()
    flow_run_repo.get.return_value = run
    policy = _policy(user, flow_run_repo=flow_run_repo)

    result = await policy.load_run(
        run_id=run.id,
        flow_id=flow_id,
        access_kind="content",
    )

    assert result == run
    flow_run_repo.get.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
        flow_id=flow_id,
    )


@pytest.mark.asyncio
async def test_load_run_allows_owner_rerun_access(user):
    flow_id = uuid4()
    run = _run(user, flow_id)
    flow_run_repo = AsyncMock()
    flow_run_repo.get.return_value = run
    policy = _policy(user, flow_run_repo=flow_run_repo)

    result = await policy.load_run(
        run_id=run.id,
        flow_id=flow_id,
        access_kind="rerun",
    )

    assert result == run


@pytest.mark.asyncio
async def test_load_run_translates_repository_missing_run_to_public_not_found(user):
    flow_id = uuid4()
    run_id = uuid4()
    flow_run_repo = AsyncMock()
    flow_run_repo.get.side_effect = FlowRunNotFoundError(
        run_id=run_id,
        tenant_id=user.tenant_id,
        flow_id=flow_id,
    )
    policy = _policy(user, flow_run_repo=flow_run_repo)

    with pytest.raises(NotFoundException) as exc_info:
        await policy.load_run(
            run_id=run_id,
            flow_id=flow_id,
            access_kind="content",
        )

    assert exc_info.value.code is None
    flow_run_repo.get.assert_awaited_once_with(
        run_id=run_id,
        tenant_id=user.tenant_id,
        flow_id=flow_id,
    )


@pytest.mark.asyncio
async def test_load_run_rejects_cross_tenant_run(user):
    flow_id = uuid4()
    run = _run(user, flow_id).model_copy(update={"tenant_id": uuid4()})
    flow_run_repo = AsyncMock()
    flow_run_repo.get.return_value = run
    policy = _policy(user, flow_run_repo=flow_run_repo)

    with pytest.raises(UnauthorizedException) as exc_info:
        await policy.load_run(
            run_id=run.id,
            flow_id=flow_id,
            access_kind="content",
        )

    assert exc_info.value.code == "flow_run_access_denied"
    assert exc_info.value.context == {"auth_layer": "tenant_isolation"}


@pytest.mark.asyncio
async def test_load_run_rejects_other_users_run_for_non_admin(user):
    flow_id = uuid4()
    run = _run(user, flow_id).model_copy(update={"principal_user_id": uuid4()})
    flow_run_repo = AsyncMock()
    flow_run_repo.get.return_value = run
    policy = _policy(user, flow_run_repo=flow_run_repo)

    with pytest.raises(UnauthorizedException) as exc_info:
        await policy.load_run(
            run_id=run.id,
            flow_id=flow_id,
            access_kind="content",
        )

    assert exc_info.value.code == "flow_run_access_denied"
    assert exc_info.value.context == {"auth_layer": "flow_run_owner"}


@pytest.mark.asyncio
async def test_load_run_allows_tenant_admin_for_other_users_run(user):
    admin_user = user.model_copy(
        update={"roles": [SimpleNamespace(permissions=[Permission.ADMIN])]}
    )
    flow_id = uuid4()
    run = _run(user, flow_id).model_copy(update={"principal_user_id": uuid4()})
    flow_run_repo = AsyncMock()
    flow_run_repo.get.return_value = run
    policy = _policy(admin_user, flow_run_repo=flow_run_repo)

    result = await policy.load_run(
        run_id=run.id,
        flow_id=flow_id,
        access_kind="content",
    )

    assert result == run


@pytest.mark.asyncio
async def test_service_key_access_requires_matching_run_principal(user):
    service_user = _service_key_user(user)
    flow_id = uuid4()
    run = _run(user, flow_id).model_copy(
        update={
            "user_id": None,
            "principal_type": PrincipalType.SERVICE_KEY.value,
            "principal_user_id": None,
            "principal_service_id": uuid4(),
            "created_by_api_key_id": uuid4(),
            "runtime_service_permission": ApiKeyPermission.WRITE,
        }
    )
    flow_run_repo = AsyncMock()
    flow_run_repo.get.return_value = run
    policy = _policy(service_user, flow_run_repo=flow_run_repo)

    with pytest.raises(UnauthorizedException) as exc_info:
        await policy.load_run(
            run_id=run.id,
            flow_id=flow_id,
            access_kind="content",
        )

    assert exc_info.value.code == "flow_run_access_denied"
    assert exc_info.value.context == {"auth_layer": "flow_run_principal"}


@pytest.mark.asyncio
async def test_service_key_evidence_view_uses_key_capability(user):
    service_user = _service_key_user(
        user,
        resource_permissions=ResourcePermissions(
            flow_evidence=ResourcePermissionLevel.READ
        ),
    )
    flow_id = uuid4()
    run = _run(user, flow_id).model_copy(
        update={
            "user_id": None,
            "principal_type": PrincipalType.SERVICE_KEY.value,
            "principal_user_id": None,
            "principal_service_id": service_user.active_api_key.service_principal_id,
            "created_by_api_key_id": service_user.active_api_key.id,
            "runtime_service_permission": ApiKeyPermission.WRITE,
        }
    )
    flow_run_repo = AsyncMock()
    flow_run_repo.get.return_value = run
    policy = _policy(service_user, flow_run_repo=flow_run_repo)

    result = await policy.load_run(
        run_id=run.id,
        flow_id=flow_id,
        access_kind="evidence_view",
    )

    assert result == run


@pytest.mark.asyncio
async def test_service_key_evidence_view_denies_missing_resource_permissions(user):
    service_user = _service_key_user(user)
    flow_id = uuid4()
    run = _run(user, flow_id).model_copy(
        update={
            "user_id": None,
            "principal_type": PrincipalType.SERVICE_KEY.value,
            "principal_user_id": None,
            "principal_service_id": service_user.active_api_key.service_principal_id,
            "created_by_api_key_id": service_user.active_api_key.id,
            "runtime_service_permission": ApiKeyPermission.WRITE,
        }
    )
    flow_run_repo = AsyncMock()
    flow_run_repo.get.return_value = run
    policy = _policy(service_user, flow_run_repo=flow_run_repo)

    with pytest.raises(UnauthorizedException) as exc_info:
        await policy.load_run(
            run_id=run.id,
            flow_id=flow_id,
            access_kind="evidence_view",
        )

    assert exc_info.value.code == "flow_run_evidence_forbidden"
    assert exc_info.value.context == {"auth_layer": "flow_run_principal"}


@pytest.mark.asyncio
async def test_can_list_all_runs_in_flow_uses_space_role(user):
    flow_repo = AsyncMock()
    flow_run_repo = AsyncMock()
    admin_policy = _policy_with_space(
        user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        role="admin",
    )
    viewer_policy = _policy_with_space(
        user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        role="viewer",
    )

    assert await admin_policy.can_list_all_runs_in_flow(flow_id=uuid4()) is True
    assert await viewer_policy.can_list_all_runs_in_flow(flow_id=uuid4()) is False


@pytest.mark.asyncio
async def test_load_space_access_returns_none_without_space_dependencies(user):
    flow_run_repo = AsyncMock()
    policy = _policy(user, flow_run_repo=flow_run_repo)

    assert await policy.load_space_access(flow_id=uuid4()) == (None, 0)


@pytest.mark.asyncio
async def test_load_run_rejects_sensitive_flow_export_when_policy_disabled(user):
    flow_id = uuid4()
    run = _run(user, flow_id)
    flow_repo = AsyncMock()
    flow_repo.get.return_value = SimpleNamespace(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        metadata_json={"care_data_policy": {"sensitive": True}},
    )
    flow_run_repo = AsyncMock()
    flow_run_repo.get.return_value = run
    policy = FlowRunAccessPolicy(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await policy.load_run(
            run_id=run.id,
            flow_id=flow_id,
            access_kind="evidence_export_redacted",
        )

    assert exc_info.value.code == "flow_run_evidence_forbidden"
    assert exc_info.value.context == {"auth_layer": "flow_runtime_policy"}


@pytest.mark.asyncio
async def test_load_run_fails_closed_on_unknown_access_kind(user):
    flow_id = uuid4()
    run = _run(user, flow_id)
    flow_run_repo = AsyncMock()
    flow_run_repo.get.return_value = run
    policy = _policy(user, flow_run_repo=flow_run_repo)

    with pytest.raises(UnauthorizedException) as exc_info:
        await policy.load_run(
            run_id=run.id,
            flow_id=flow_id,
            access_kind=cast(FlowRunAccessKind, "unknown_access_kind"),
        )

    assert exc_info.value.code == "flow_run_access_denied"
    assert exc_info.value.context == {"auth_layer": "flow_run_access_kind"}


def _sensitive_metadata() -> dict[str, object]:
    return {"care_data_policy": {"sensitive": True}}


def _disclosure_policy(
    user,
    *,
    metadata_json: dict[str, object] | None = None,
    security_level: int = 0,
    role: str = "owner",
) -> tuple[FlowRunAccessPolicy, FlowRun]:
    flow_run_repo = AsyncMock()
    flow_repo = AsyncMock()
    policy = _policy_with_space(
        user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        role=role,
        security_level=security_level,
    )
    flow = flow_repo.get.return_value
    flow_repo.get.return_value = SimpleNamespace(
        id=flow.id,
        tenant_id=flow.tenant_id,
        space_id=flow.space_id,
        metadata_json=metadata_json,
    )
    # The disclosure decision reads the narrow evidence-access context, so the
    # double answers it with the real typed value rather than a mock.
    flow_repo.get_evidence_access_context.return_value = FlowEvidenceAccessContext(
        flow_id=flow.id,
        space_id=flow.space_id,
        sensitive=flow_metadata_marks_sensitive(metadata_json),
        classification_level=security_level,
    )
    run = _run(user, flow_repo.get.return_value.id)
    flow_run_repo.get.return_value = run
    return policy, run


def _tenant_admin(user):
    return user.model_copy(update={"permissions": {Permission.ADMIN}})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "access_kind",
    ["evidence_view", "evidence_export_redacted", "evidence_export_raw"],
)
async def test_ordinary_flow_discloses_passage_text_on_every_surface(
    user, access_kind: FlowRunAccessKind
) -> None:
    policy, run = _disclosure_policy(user)

    assert (
        await policy.passage_disclosure_for_run(run, access_kind=access_kind)
        == "text_disclosed"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("access_kind", "expected"),
    [
        ("evidence_view", "text_withheld_sensitive_flow"),
        ("evidence_export_redacted", "text_withheld_sensitive_flow"),
        ("evidence_export_raw", "text_disclosed"),
    ],
)
async def test_sensitive_flow_withholds_passage_text_below_raw_export(
    user, access_kind: FlowRunAccessKind, expected: str
) -> None:
    policy, run = _disclosure_policy(user, metadata_json=_sensitive_metadata())

    assert (
        await policy.passage_disclosure_for_run(run, access_kind=access_kind)
        == expected
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("access_kind", "expected"),
    [
        ("evidence_view", "text_withheld_classified_space"),
        ("evidence_export_redacted", "text_withheld_classified_space"),
        ("evidence_export_raw", "text_disclosed"),
    ],
)
async def test_classified_space_withholds_passage_text_below_raw_export(
    user, access_kind: FlowRunAccessKind, expected: str
) -> None:
    policy, run = _disclosure_policy(user, security_level=3)

    assert (
        await policy.passage_disclosure_for_run(run, access_kind=access_kind)
        == expected
    )


@pytest.mark.asyncio
async def test_service_principal_sees_the_same_disclosure_decision(user) -> None:
    service_user = _service_key_user(
        user,
        resource_permissions=ResourcePermissions(
            flow_evidence=ResourcePermissionLevel.READ
        ),
    )
    policy, run = _disclosure_policy(
        service_user,
        metadata_json=_sensitive_metadata(),
        role="admin",
    )

    assert (
        await policy.passage_disclosure_for_run(run, access_kind="evidence_view")
        == "text_withheld_sensitive_flow"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("access_kind", "expected"),
    [
        ("evidence_view", "text_withheld_classified_space"),
        ("evidence_export_redacted", "text_withheld_classified_space"),
        ("evidence_export_raw", "text_disclosed"),
    ],
)
async def test_tenant_admin_still_withholds_text_in_a_classified_space(
    user, access_kind: FlowRunAccessKind, expected: str
) -> None:
    """A tenant admin bypasses authorization, never the data's classification."""
    policy, run = _disclosure_policy(_tenant_admin(user), security_level=3)

    assert (
        await policy.passage_disclosure_for_run(run, access_kind=access_kind)
        == expected
    )


@pytest.mark.asyncio
async def test_tenant_admin_still_withholds_text_for_a_sensitive_flow(user) -> None:
    policy, run = _disclosure_policy(
        _tenant_admin(user), metadata_json=_sensitive_metadata()
    )

    assert (
        await policy.passage_disclosure_for_run(run, access_kind="evidence_view")
        == "text_withheld_sensitive_flow"
    )


@pytest.mark.asyncio
async def test_disclosure_never_reads_the_space_through_the_membership_check(
    user,
) -> None:
    """The decision must not add an authorization side effect of its own."""
    policy, run = _disclosure_policy(_tenant_admin(user), security_level=3)
    space_service = policy.space_service
    assert space_service is not None

    await policy.passage_disclosure_for_run(run, access_kind="evidence_view")

    cast(AsyncMock, space_service).get_space.assert_not_awaited()
    cast(AsyncMock, policy.flow_repo).get.assert_not_awaited()
