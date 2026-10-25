from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast, get_args
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.authentication.auth_models import (
    ApiKeyOwnership,
    ApiKeyPermission,
    ResourcePermissionLevel,
    ResourcePermissions,
)
from eneo.authentication.principal_types import PrincipalType
from eneo.authentication.service_key_user import build_service_key_user
from eneo.flows.application.flow_run_access_policy import (
    FlowRunAccessKind,
    FlowRunAccessPolicy,
)
from eneo.flows.domain.flow import FlowRun, FlowRunStatus, FlowRunStatusSnapshot
from eneo.flows.domain.flow_run_exceptions import FlowRunNotFoundError
from eneo.flows.flow_evidence_policy import (
    FlowEvidencePolicy,
    FlowHistoryAccessContext,
    flow_evidence_metadata_facts,
)
from eneo.main.exceptions import NotFoundException, UnauthorizedException
from eneo.roles.permissions import Permission
from tests.unit.api_key_test_utils import make_api_key


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
        # What the executor records before a run's first step.
        evidence_classification_level=0,
        created_at=now,
        updated_at=now,
    )


def _service_key_user(
    user,
    *,
    resource_permissions: ResourcePermissions | None = None,
    tenant_admin: bool = False,
):
    service_key = make_api_key(
        default_permission=(
            ApiKeyPermission.ADMIN if tenant_admin else ApiKeyPermission.WRITE
        ),
        ownership=ApiKeyOwnership.SERVICE,
        owner_user_id=None,
        resource_permissions=resource_permissions,
        tenant_id=user.tenant_id,
        service_principal_id=uuid4(),
    )
    return build_service_key_user(
        key=service_key,
        tenant=user.tenant,
        permissions={Permission.ADMIN} if tenant_admin else None,
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
    evidence_export_allowed: bool = True,
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
    actor_manager.get_space_actor.return_value = SimpleNamespace(
        get_current_role=lambda: role
    )
    flow_repo.get.return_value = flow
    flow_repo.get_history_access_context.return_value = FlowHistoryAccessContext(
        flow_id=flow.id,
        space_id=space.id,
        published=True,
        retired=False,
        sensitive=False,
        evidence_export_allowed=evidence_export_allowed,
        classification_level=security_level,
    )
    space_service.get_space_access_facts.return_value = space
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

    assert str(exc_info.value) == "Flow run not found."
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
async def test_admin_service_key_access_requires_matching_run_principal(user):
    service_user = _service_key_user(
        user,
        resource_permissions=ResourcePermissions(
            flow_evidence=ResourcePermissionLevel.ADMIN
        ),
        tenant_admin=True,
    )
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
            access_kind="evidence_view",
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
@pytest.mark.parametrize(
    "access_kind",
    ["evidence_view", "evidence_export_raw"],
)
async def test_admin_service_key_evidence_access_requires_key_capability(
    user,
    access_kind: FlowRunAccessKind,
):
    service_user = _service_key_user(user, tenant_admin=True)
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
    cast(
        AsyncMock, policy.flow_repo
    ).get_history_access_context.return_value = FlowHistoryAccessContext(
        flow_id=flow_id,
        space_id=uuid4(),
        published=True,
        retired=False,
        sensitive=False,
        evidence_export_allowed=True,
        classification_level=0,
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await policy.load_run(
            run_id=run.id,
            flow_id=flow_id,
            access_kind=access_kind,
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


def _export_switch_case(user, principal: str, *, evidence_export_allowed: bool):
    """A caller who passes every rule behind the flow's export switch."""
    acting_user = user
    if principal == "tenant_admin":
        acting_user = _tenant_admin(user)
    elif principal == "service_key":
        acting_user = _service_key_user(
            user,
            resource_permissions=ResourcePermissions(
                flow_evidence=ResourcePermissionLevel.ADMIN
            ),
            tenant_admin=True,
        )
    flow_repo = AsyncMock()
    policy = _policy_with_space(
        acting_user,
        flow_repo=flow_repo,
        flow_run_repo=AsyncMock(),
        role="owner",
        evidence_export_allowed=evidence_export_allowed,
    )
    run = _run(user, flow_repo.get.return_value.id)
    if principal == "service_key":
        run = run.model_copy(
            update={
                "user_id": None,
                "principal_type": PrincipalType.SERVICE_KEY.value,
                "principal_user_id": None,
                "principal_service_id": (
                    acting_user.active_api_key.service_principal_id
                ),
                "created_by_api_key_id": acting_user.active_api_key.id,
            }
        )
    return policy, run, flow_repo


@pytest.mark.asyncio
@pytest.mark.parametrize("principal", ["run_owner", "tenant_admin", "service_key"])
@pytest.mark.parametrize(
    "access_kind", ["evidence_export_redacted", "evidence_export_raw"]
)
async def test_export_is_refused_for_everyone_until_the_flow_allows_it(
    user, principal: str, access_kind: FlowRunAccessKind
) -> None:
    policy, run, flow_repo = _export_switch_case(
        user, principal, evidence_export_allowed=False
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await policy.ensure_can_access_run(run, access_kind=access_kind)

    assert str(exc_info.value) == "Evidence export is turned off for this flow."
    assert exc_info.value.code == "flow_run_evidence_export_disabled"
    assert exc_info.value.context == {"auth_layer": "flow_evidence_policy"}
    flow_repo.get_history_access_context.assert_awaited_once_with(
        flow_id=run.flow_id,
        tenant_id=user.tenant_id,
        include_retired=False,
    )


def _caller_who_may_not_export(user, caller: str, *, evidence_export_allowed: bool):
    """A caller the ordinary rules refuse, and the refusal those rules give."""
    flow_repo = AsyncMock()
    acting_user = user
    if caller != "another_users_run":
        acting_user = _service_key_user(
            user,
            resource_permissions=ResourcePermissions(
                flow_evidence=ResourcePermissionLevel.READ
            ),
        )
    policy = _policy_with_space(
        acting_user,
        flow_repo=flow_repo,
        flow_run_repo=AsyncMock(),
        role="viewer",
        evidence_export_allowed=evidence_export_allowed,
    )
    run = _run(user, flow_repo.get.return_value.id)
    if caller == "another_users_run":
        run = run.model_copy(update={"principal_user_id": uuid4()})
        return policy, run, ("flow_run_access_denied", "flow_run_owner")
    key = acting_user.active_api_key
    run = run.model_copy(
        update={
            "user_id": None,
            "principal_type": PrincipalType.SERVICE_KEY.value,
            "principal_user_id": None,
            "principal_service_id": (
                uuid4() if caller == "another_keys_run" else key.service_principal_id
            ),
            "created_by_api_key_id": key.id,
        }
    )
    if caller == "another_keys_run":
        return policy, run, ("flow_run_access_denied", "flow_run_principal")
    return policy, run, ("flow_run_evidence_forbidden", "flow_run_principal")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "caller", ["another_users_run", "another_keys_run", "view_only_key"]
)
@pytest.mark.parametrize(
    "access_kind", ["evidence_export_redacted", "evidence_export_raw"]
)
async def test_a_caller_who_may_not_export_cannot_tell_how_the_switch_is_set(
    user, caller: str, access_kind: FlowRunAccessKind
) -> None:
    refusals = []
    for allowed in (False, True):
        policy, run, expected = _caller_who_may_not_export(
            user, caller, evidence_export_allowed=allowed
        )

        with pytest.raises(UnauthorizedException) as exc_info:
            await policy.ensure_can_access_run(run, access_kind=access_kind)

        refusal = (exc_info.value.code, exc_info.value.context["auth_layer"])
        assert refusal == expected
        refusals.append((refusal, str(exc_info.value)))

    assert refusals[0] == refusals[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("principal", ["run_owner", "tenant_admin", "service_key"])
async def test_evidence_can_be_viewed_while_export_is_off(user, principal: str) -> None:
    policy, run, _ = _export_switch_case(user, principal, evidence_export_allowed=False)

    await policy.ensure_can_access_run(run, access_kind="evidence_view")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "access_kind", ["evidence_export_redacted", "evidence_export_raw"]
)
async def test_a_sensitive_flow_exports_once_its_own_switch_is_on(
    user, access_kind: FlowRunAccessKind
) -> None:
    # A sensitive flow has no export gate of its own: no tenant setting stands
    # behind the flow's switch.
    policy, run, flow_repo = _export_switch_case(
        user, "run_owner", evidence_export_allowed=True
    )
    flow_repo.get_history_access_context.return_value = replace(
        flow_repo.get_history_access_context.return_value, sensitive=True
    )

    await policy.ensure_can_access_run(run, access_kind=access_kind)


@pytest.mark.asyncio
async def test_a_retired_flow_keeps_the_export_switch_it_was_deleted_with(user) -> None:
    for allowed in (True, False):
        policy, run, flow_repo = _export_switch_case(
            user, "run_owner", evidence_export_allowed=allowed
        )
        flow_repo.get_history_access_context.return_value = replace(
            flow_repo.get_history_access_context.return_value, retired=True
        )

        if allowed:
            await policy.ensure_can_access_run(
                run, access_kind="evidence_export_redacted", history=True
            )
        else:
            with pytest.raises(UnauthorizedException) as exc_info:
                await policy.ensure_can_access_run(
                    run, access_kind="evidence_export_redacted", history=True
                )
            assert exc_info.value.code == "flow_run_evidence_export_disabled"
        flow_repo.get_history_access_context.assert_awaited_with(
            flow_id=run.flow_id,
            tenant_id=user.tenant_id,
            include_retired=True,
        )


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
    flow_repo.get_history_access_context.return_value = FlowHistoryAccessContext(
        flow_id=flow.id,
        space_id=flow.space_id,
        published=True,
        retired=False,
        sensitive=flow_evidence_metadata_facts(metadata_json).sensitive,
        evidence_export_allowed=True,
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

    cast(AsyncMock, space_service).get_space_access_facts.assert_not_awaited()
    cast(AsyncMock, policy.flow_repo).get.assert_not_awaited()


@pytest.mark.parametrize(
    ("permission_level", "allowed_access"),
    [
        (
            ResourcePermissionLevel.READ,
            {"status", "cancel", "content", "artifact", "evidence_view"},
        ),
        (
            ResourcePermissionLevel.WRITE,
            {
                "status",
                "cancel",
                "content",
                "artifact",
                "evidence_view",
                "evidence_export_redacted",
            },
        ),
        (
            ResourcePermissionLevel.ADMIN,
            {
                "status",
                "cancel",
                "content",
                "artifact",
                "evidence_view",
                "evidence_export_redacted",
                "evidence_export_raw",
            },
        ),
    ],
)
async def test_service_key_access_matrix_is_capability_exact(
    user,
    permission_level: ResourcePermissionLevel,
    allowed_access: set[FlowRunAccessKind],
) -> None:
    service_user = _service_key_user(
        user,
        resource_permissions=ResourcePermissions(flow_evidence=permission_level),
    )
    flow_repo = AsyncMock()
    flow_run_repo = AsyncMock()
    policy = _policy_with_space(
        service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        role="viewer",
    )
    flow = flow_repo.get.return_value
    flow_repo.get_history_access_context.return_value = FlowHistoryAccessContext(
        flow_id=flow.id,
        space_id=flow.space_id,
        published=True,
        retired=False,
        sensitive=False,
        evidence_export_allowed=True,
        classification_level=0,
    )
    run = _run(user, flow.id).model_copy(
        update={
            "user_id": None,
            "principal_type": PrincipalType.SERVICE_KEY.value,
            "principal_user_id": None,
            "principal_service_id": service_user.active_api_key.service_principal_id,
            "created_by_api_key_id": service_user.active_api_key.id,
            "runtime_service_permission": ApiKeyPermission.WRITE,
        }
    )

    for access_kind in get_args(FlowRunAccessKind):
        if access_kind in allowed_access:
            await policy.ensure_can_access_run(run, access_kind=access_kind)
            continue
        with pytest.raises(UnauthorizedException) as exc_info:
            await policy.ensure_can_access_run(run, access_kind=access_kind)
        expected_message = {
            "evidence_view": (
                "Service principal is not authorized to view evidence for this run."
            ),
            "evidence_export_redacted": (
                "Service principal is not authorized to export evidence for this run."
            ),
            "evidence_export_raw": (
                "Service principal is not authorized to export raw evidence for this run."
            ),
        }[access_kind]
        assert str(exc_info.value) == expected_message
        assert exc_info.value.code == "flow_run_evidence_forbidden"
        assert exc_info.value.context == {"auth_layer": "flow_run_principal"}


@pytest.mark.parametrize(
    ("role", "security_level", "denied_access"),
    [
        ("admin", 0, set()),
        ("admin", 3, {"evidence_export_raw"}),
        ("owner", 3, set()),
    ],
)
async def test_space_manager_access_matrix_is_role_and_classification_exact(
    user,
    role: str,
    security_level: int,
    denied_access: set[FlowRunAccessKind],
) -> None:
    flow_repo = AsyncMock()
    policy = _policy_with_space(
        user,
        flow_repo=flow_repo,
        flow_run_repo=AsyncMock(),
        role=role,
        security_level=security_level,
    )
    flow = flow_repo.get.return_value
    flow_repo.get_history_access_context.return_value = FlowHistoryAccessContext(
        flow_id=flow.id,
        space_id=flow.space_id,
        published=True,
        retired=False,
        sensitive=False,
        evidence_export_allowed=True,
        classification_level=security_level,
    )
    run = _run(user, flow.id).model_copy(update={"principal_user_id": uuid4()})

    for access_kind in get_args(FlowRunAccessKind):
        if access_kind in denied_access:
            with pytest.raises(UnauthorizedException) as exc_info:
                await policy.ensure_can_access_run(run, access_kind=access_kind)
            assert str(exc_info.value) == (
                "Raw evidence export is not allowed for space admins when the "
                "run's evidence is held to classification 3."
            )
            assert exc_info.value.code == "flow_run_evidence_raw_export_forbidden"
            assert exc_info.value.context == {"auth_layer": "space_membership"}
            continue
        await policy.ensure_can_access_run(run, access_kind=access_kind)


@pytest.mark.parametrize(
    ("caller", "refusal_layer"),
    [
        # Kill the mutants that leave one raw-export gate on the space's level
        # as it is now (1) instead of the level the run recorded (3).
        ("service_key", "flow_run_principal"),
        ("space_admin", "space_membership"),
        # Kill the mutants that hold the exempt roles to the recorded level, or
        # that ignore the tenant's classification-3 switch for space admins.
        ("space_owner", None),
        ("tenant_admin", None),
        ("space_admin_allowed_by_tenant", None),
    ],
)
async def test_raw_export_is_held_to_the_level_the_run_recorded(
    user, caller: str, refusal_layer: str | None
) -> None:
    acting_user = user
    if caller == "tenant_admin":
        acting_user = user.model_copy(
            update={"roles": [SimpleNamespace(permissions=[Permission.ADMIN])]}
        )
    elif caller == "service_key":
        acting_user = _service_key_user(
            user,
            resource_permissions=ResourcePermissions(
                flow_evidence=ResourcePermissionLevel.ADMIN
            ),
        )
    elif caller == "space_admin_allowed_by_tenant":
        acting_user = user.model_copy(
            update={
                "tenant": user.tenant.model_copy(
                    update={
                        "flow_settings": {
                            "evidence_policy": {
                                "classification_3": {
                                    "allow_space_admin_raw_export": True
                                }
                            }
                        }
                    }
                )
            }
        )
    flow_repo = AsyncMock()
    policy = _policy_with_space(
        acting_user,
        flow_repo=flow_repo,
        flow_run_repo=AsyncMock(),
        role={
            "space_admin": "admin",
            "space_admin_allowed_by_tenant": "admin",
            "space_owner": "owner",
        }.get(caller, "viewer"),
        security_level=1,
    )
    run = _run(user, flow_repo.get.return_value.id).model_copy(
        update={"evidence_classification_level": 3, "principal_user_id": uuid4()}
    )
    if caller == "service_key":
        run = run.model_copy(
            update={
                "principal_type": PrincipalType.SERVICE_KEY.value,
                "principal_user_id": None,
                "principal_service_id": (
                    acting_user.active_api_key.service_principal_id
                ),
                "created_by_api_key_id": acting_user.active_api_key.id,
            }
        )

    if refusal_layer is None:
        await policy.ensure_can_access_run(run, access_kind="evidence_export_raw")
        return
    with pytest.raises(UnauthorizedException) as exc_info:
        await policy.ensure_can_access_run(run, access_kind="evidence_export_raw")
    assert exc_info.value.code == "flow_run_evidence_raw_export_forbidden"
    assert exc_info.value.context == {"auth_layer": refusal_layer}


async def test_a_run_without_a_recorded_level_answers_to_a_classified_space(
    user,
) -> None:
    """Kills: an unrecorded run that produced no evidence yet (queued, or
    failed in preflight) leaving its classification-3 space's rule behind, so a
    space admin could raw-export its input."""
    flow_repo = AsyncMock()
    flow_run_repo = AsyncMock()
    flow_run_repo.has_step_attempts.return_value = False
    policy = _policy_with_space(
        user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        role="admin",
        security_level=3,
    )
    run = _run(user, flow_repo.get.return_value.id).model_copy(
        update={"evidence_classification_level": None, "principal_user_id": uuid4()}
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await policy.ensure_can_access_run(run, access_kind="evidence_export_raw")
    assert exc_info.value.code == "flow_run_evidence_raw_export_forbidden"
    assert exc_info.value.context == {"auth_layer": "space_membership"}


@pytest.mark.parametrize("access_kind", list(get_args(FlowRunAccessKind)))
async def test_cross_tenant_run_is_denied_before_every_access_surface(
    user,
    access_kind: FlowRunAccessKind,
) -> None:
    run = _run(user, uuid4()).model_copy(update={"tenant_id": uuid4()})
    policy = _policy(user, flow_run_repo=AsyncMock())

    with pytest.raises(UnauthorizedException) as exc_info:
        await policy.ensure_can_access_run(run, access_kind=access_kind)

    assert str(exc_info.value) == "You do not have access to this flow run."
    assert exc_info.value.code == "flow_run_access_denied"
    assert exc_info.value.context == {"auth_layer": "tenant_isolation"}


@pytest.mark.parametrize(
    ("method_name", "expected_code"),
    [
        ("deny_run_access", "flow_run_access_denied"),
        ("deny_evidence_access", "flow_run_evidence_forbidden"),
        ("deny_evidence_export_disabled", "flow_run_evidence_export_disabled"),
        ("deny_raw_export_access", "flow_run_evidence_raw_export_forbidden"),
    ],
)
def test_access_denials_preserve_message_code_and_layer(
    method_name: str,
    expected_code: str,
) -> None:
    method = getattr(FlowRunAccessPolicy, method_name)
    kwargs = {"auth_layer": "test_layer"}
    if method_name in {"deny_evidence_access", "deny_raw_export_access"}:
        kwargs["message"] = "Exact denial message."

    with pytest.raises(UnauthorizedException) as exc_info:
        method(**kwargs)

    expected_message = {
        "deny_run_access": "You do not have access to this flow run.",
        "deny_evidence_export_disabled": "Evidence export is turned off for this flow.",
    }.get(method_name, "Exact denial message.")
    assert str(exc_info.value) == expected_message
    assert exc_info.value.code == expected_code
    assert exc_info.value.context == {"auth_layer": "test_layer"}


async def test_space_and_flow_context_lookups_are_cached_per_flow(user) -> None:
    flow_repo = AsyncMock()
    policy = _policy_with_space(
        user,
        flow_repo=flow_repo,
        flow_run_repo=AsyncMock(),
        role="owner",
        security_level=2,
    )
    context = flow_repo.get_history_access_context.return_value

    for _ in range(2):
        assert await policy.load_space_access(flow_id=context.flow_id) == (
            policy.actor_manager.get_space_actor.return_value,
            2,
        )
        assert (
            await policy.load_flow_context(flow_id=context.flow_id, history=False)
            == context
        )

    # The caller's facts and the flow row are each read once; no space
    # aggregate and no flow aggregate.
    cast(AsyncMock, flow_repo.get).assert_not_awaited()
    cast(
        AsyncMock, policy.space_service.get_space_access_facts
    ).assert_awaited_once_with(context.space_id)
    cast(AsyncMock, flow_repo.get_history_access_context).assert_awaited_once_with(
        flow_id=context.flow_id,
        tenant_id=user.tenant_id,
        include_retired=False,
    )


async def test_live_read_refuses_a_retired_flow_whose_space_a_history_read_cached(
    user,
) -> None:
    flow_repo = AsyncMock()
    policy = _policy_with_space(
        user, flow_repo=flow_repo, flow_run_repo=AsyncMock(), role="owner"
    )
    retired = replace(flow_repo.get_history_access_context.return_value, retired=True)

    async def history_row(*, flow_id, tenant_id, include_retired):
        _ = (flow_id, tenant_id)
        if not include_retired:
            raise NotFoundException("Flow not found.")
        return retired

    flow_repo.get_history_access_context.side_effect = history_row

    actor, _level = await policy.load_space_access(
        flow_id=retired.flow_id, history=True
    )
    assert actor is policy.actor_manager.get_space_actor.return_value
    with pytest.raises(NotFoundException):
        await policy.load_space_access(flow_id=retired.flow_id)
    with pytest.raises(NotFoundException):
        await policy.can_list_all_runs_in_flow(flow_id=retired.flow_id)
    assert await policy.can_list_all_runs_in_flow(flow_id=retired.flow_id, history=True)


async def test_history_read_cannot_authorize_a_mutation(user) -> None:
    flow_repo = AsyncMock()
    policy = _policy_with_space(
        user, flow_repo=flow_repo, flow_run_repo=AsyncMock(), role="owner"
    )
    run = _run(user, flow_repo.get_history_access_context.return_value.flow_id)

    with pytest.raises(NotFoundException):
        await policy.ensure_can_access_run(run, access_kind="cancel", history=True)

    cast(AsyncMock, flow_repo.get_history_access_context).assert_not_awaited()
    await policy.ensure_can_access_run(run, access_kind="cancel")


async def test_service_key_raw_export_fails_closed_in_classification_three(
    user,
) -> None:
    service_user = _service_key_user(
        user,
        resource_permissions=ResourcePermissions(
            flow_evidence=ResourcePermissionLevel.ADMIN
        ),
    )
    flow_repo = AsyncMock()
    policy = _policy_with_space(
        service_user,
        flow_repo=flow_repo,
        flow_run_repo=AsyncMock(),
        role="viewer",
        security_level=3,
    )
    flow = flow_repo.get.return_value
    flow_repo.get_history_access_context.return_value = FlowHistoryAccessContext(
        flow_id=flow.id,
        space_id=flow.space_id,
        published=True,
        retired=False,
        sensitive=False,
        evidence_export_allowed=True,
        classification_level=3,
    )
    run = _run(user, flow.id).model_copy(
        update={
            "user_id": None,
            "principal_type": PrincipalType.SERVICE_KEY.value,
            "principal_user_id": None,
            "principal_service_id": service_user.active_api_key.service_principal_id,
            "created_by_api_key_id": service_user.active_api_key.id,
        }
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await policy.ensure_can_access_run(run, access_kind="evidence_export_raw")

    assert str(exc_info.value) == (
        "Raw evidence export is not allowed for service principals when the "
        "run's evidence is held to classification 3."
    )
    assert exc_info.value.code == "flow_run_evidence_raw_export_forbidden"
    assert exc_info.value.context == {"auth_layer": "flow_run_principal"}
    cast(
        AsyncMock, policy.space_service
    ).get_space_access_facts.assert_awaited_once_with(flow.space_id)


def test_evidence_policy_reads_only_the_tenant_flow_settings(user) -> None:
    tenant = user.tenant.model_copy(
        update={
            "flow_settings": {
                "evidence_policy": {
                    "version": 1,
                    "classification_3": {
                        "allow_space_admin_raw_export": True,
                        "allow_run_owner_raw_export": True,
                        "allow_service_key_raw_export": True,
                    },
                }
            }
        }
    )
    configured_user = user.model_copy(update={"tenant": tenant})
    policy = _policy(configured_user, flow_run_repo=AsyncMock())

    assert policy._evidence_policy() == FlowEvidencePolicy(
        allow_space_admin_raw_export_class3=True,
        allow_run_owner_raw_export_class3=True,
        allow_service_key_raw_export_class3=True,
    )


def _status_snapshot(run: FlowRun) -> FlowRunStatusSnapshot:
    return FlowRunStatusSnapshot.model_validate(
        run.model_dump(include=set(FlowRunStatusSnapshot.model_fields))
    )


def _content_readers(
    user, caller: str
) -> tuple[FlowRunAccessPolicy, FlowRunAccessPolicy, FlowRun]:
    """Two policies for ``caller`` over one run, each with its own memo and
    repositories that answer both the complete row and the status projection
    with speaker labels: one to ask, one to ask the reference question."""
    reader = user
    if caller == "tenant_admin":
        reader = user.model_copy(
            update={"roles": [SimpleNamespace(permissions=[Permission.ADMIN])]}
        )
    elif caller.startswith("service_key"):
        reader = _service_key_user(user)
    role = {"space_owner": "owner", "space_admin": "admin"}.get(caller, "viewer")
    run: FlowRun | None = None
    policies: list[FlowRunAccessPolicy] = []
    for _ in range(2):
        flow_repo = AsyncMock()
        flow_run_repo = AsyncMock()
        policies.append(
            _policy_with_space(
                reader, flow_repo=flow_repo, flow_run_repo=flow_run_repo, role=role
            )
        )
        if run is None:
            run = _run(user, flow_repo.get_history_access_context.return_value.flow_id)
            if caller != "run_owner":
                run = run.model_copy(update={"principal_user_id": uuid4()})
            if caller.startswith("service_key"):
                run = run.model_copy(
                    update={
                        "principal_type": PrincipalType.SERVICE_KEY,
                        "principal_user_id": None,
                        "principal_service_id": (
                            reader.active_api_key.service_principal_id
                            if caller == "service_key_matching"
                            else uuid4()
                        ),
                    }
                )
        else:
            context = flow_repo.get_history_access_context.return_value
            flow_repo.get_history_access_context.return_value = replace(
                context, flow_id=run.flow_id
            )
        flow_run_repo.get.return_value = run
        flow_run_repo.get_status.return_value = _status_snapshot(run)
        flow_run_repo.get_status_with_speaker_labels.return_value = (
            _status_snapshot(run),
            True,
        )
    assert run is not None
    policy, reference = policies
    return policy, reference, run


async def _outcome(load) -> object:
    try:
        await load
    except (NotFoundException, UnauthorizedException) as exc:
        return (type(exc), str(exc), exc.code, getattr(exc, "context", None))
    return "granted"


_CONTENT_READERS = (
    "run_owner",
    "space_owner",
    "space_admin",
    "space_member",
    "tenant_admin",
    "service_key_matching",
    "service_key_other",
)


@pytest.mark.parametrize("caller", _CONTENT_READERS)
@pytest.mark.parametrize("history", [False, True])
async def test_status_with_speaker_labels_grants_and_denies_as_a_content_read(
    user, caller: str, history: bool
) -> None:
    policy, reference, run = _content_readers(user, caller)

    expected = await _outcome(
        reference.load_run(
            run_id=run.id, flow_id=run.flow_id, access_kind="content", history=history
        )
    )
    outcome = await _outcome(
        policy.load_run_status_with_speaker_labels(
            run_id=run.id, flow_id=run.flow_id, access_kind="content", history=history
        )
    )

    assert outcome == expected
    assert (expected == "granted") is (
        caller not in {"space_member", "service_key_other"}
    )
    repo = cast(AsyncMock, policy.flow_run_repo)
    repo.get.assert_not_awaited()
    repo.get_status_with_speaker_labels.assert_awaited_once_with(
        run_id=run.id, tenant_id=policy.user.tenant_id, flow_id=run.flow_id
    )


async def test_status_with_speaker_labels_returns_the_projection(user) -> None:
    policy, _reference, run = _content_readers(user, "run_owner")

    snapshot, speaker_labels = await policy.load_run_status_with_speaker_labels(
        run_id=run.id, flow_id=run.flow_id, access_kind="content"
    )

    assert snapshot == _status_snapshot(run)
    assert speaker_labels is True


async def test_status_with_speaker_labels_answers_a_missing_run_not_found(
    user,
) -> None:
    policy, _reference, run = _content_readers(user, "run_owner")
    cast(
        AsyncMock, policy.flow_run_repo
    ).get_status_with_speaker_labels.side_effect = FlowRunNotFoundError(
        run_id=run.id, tenant_id=user.tenant_id, flow_id=run.flow_id
    )

    with pytest.raises(NotFoundException) as exc_info:
        await policy.load_run_status_with_speaker_labels(
            run_id=run.id, flow_id=run.flow_id, access_kind="content"
        )

    assert str(exc_info.value) == "Flow run not found."
    assert exc_info.value.code is None


async def test_status_with_speaker_labels_refuses_an_unknown_kind_and_a_history_mutation(
    user,
) -> None:
    policy, _reference, run = _content_readers(user, "run_owner")

    with pytest.raises(UnauthorizedException) as exc_info:
        await policy.load_run_status_with_speaker_labels(
            run_id=run.id,
            flow_id=run.flow_id,
            access_kind=cast(FlowRunAccessKind, "unknown_access_kind"),
        )
    assert exc_info.value.code == "flow_run_access_denied"
    assert exc_info.value.context == {"auth_layer": "flow_run_access_kind"}

    with pytest.raises(NotFoundException) as not_found:
        await policy.load_run_status_with_speaker_labels(
            run_id=run.id, flow_id=run.flow_id, access_kind="cancel", history=True
        )
    assert str(not_found.value) == "Flow not found."


@pytest.mark.parametrize("caller", _CONTENT_READERS)
async def test_load_run_status_takes_the_access_kind_it_is_asked_for(
    user, caller: str
) -> None:
    policy, reference, run = _content_readers(user, caller)

    expected = await _outcome(
        reference.load_run(run_id=run.id, flow_id=run.flow_id, access_kind="content")
    )
    outcome = await _outcome(
        policy.load_run_status(
            run_id=run.id, flow_id=run.flow_id, access_kind="content"
        )
    )

    assert outcome == expected
    cast(AsyncMock, policy.flow_run_repo).get.assert_not_awaited()
