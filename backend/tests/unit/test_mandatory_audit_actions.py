"""Mandatory audit actions: always logged, written in the caller's
transaction, and locked in the tenant's audit configuration."""

from collections.abc import Iterator
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.dependencies.models import Dependant

from eneo.audit.application.audit_config_service import AuditConfigService
from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.audit_log import AuditLog
from eneo.audit.domain.category_mappings import CATEGORY_MAPPINGS
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.domain.mandatory_actions import MANDATORY_AUDIT_ACTIONS
from eneo.audit.schemas.audit_config_schemas import ActionUpdate
from eneo.database.database import get_session_with_transaction
from eneo.main.exceptions import BadRequestException
from tests.unit.api_key_test_utils import runtime_router_routes

MANDATORY = sorted(MANDATORY_AUDIT_ACTIONS, key=lambda action: action.value)


def test_the_mandatory_set_is_oversight_group_membership_and_widget_publishing():
    assert MANDATORY_AUDIT_ACTIONS == {
        ActionType.SPACE_OVERSIGHT_JOINED,
        ActionType.SPACE_OVERSIGHT_LEFT,
        ActionType.SPACE_OVERSIGHT_MEMBER_ADDED,
        ActionType.SPACE_OVERSIGHT_MEMBER_ROLE_CHANGED,
        ActionType.SPACE_OVERSIGHT_MEMBER_REMOVED,
        ActionType.USER_GROUP_MEMBER_ADDED,
        ActionType.USER_GROUP_MEMBER_REMOVED,
        ActionType.WIDGET_ACTIVATION_REQUEST_DECLINED,
        ActionType.WIDGET_ACTIVATED,
        ActionType.WIDGET_PAUSED,
        ActionType.WIDGET_ARCHIVED,
    }
    # Editor workflow events stay configurable.
    assert ActionType.WIDGET_ACTIVATION_REQUESTED not in MANDATORY_AUDIT_ACTIONS
    assert ActionType.WIDGET_ACTIVATION_REQUEST_WITHDRAWN not in MANDATORY_AUDIT_ACTIONS


@pytest.mark.parametrize("action", MANDATORY)
def test_mandatory_actions_are_admin_actions(action):
    assert action in set(ActionType)
    assert CATEGORY_MAPPINGS[action.value] == "admin_actions"


def _silenced_audit_service(repository=None) -> AuditService:
    """Kill switch off, category off and every action override off."""
    feature_flags = AsyncMock()
    feature_flags.check_is_feature_enabled.return_value = False
    config = AsyncMock()
    config.is_action_enabled.return_value = False
    return AuditService(
        repository or AsyncMock(),
        audit_config_service=config,
        feature_flag_service=feature_flags,
    )


@pytest.mark.parametrize("action", MANDATORY)
async def test_mandatory_actions_are_logged_whatever_the_configuration(action):
    service = _silenced_audit_service()

    assert await service._should_log_action(uuid4(), action) is True
    service.feature_flag_service.check_is_feature_enabled.assert_not_called()
    service.audit_config_service.is_action_enabled.assert_not_called()


async def test_other_actions_still_follow_the_configuration():
    service = _silenced_audit_service()

    assert (
        await service._should_log_action(
            uuid4(), ActionType.WIDGET_ACTIVATION_REQUESTED
        )
        is False
    )


def _required_kwargs(action: ActionType) -> dict:
    return dict(
        tenant_id=uuid4(),
        actor_id=uuid4(),
        action=action,
        entity_type=EntityType.SPACE,
        entity_id=uuid4(),
        description="Joined space 'Socialtjänst' as viewer through oversight",
        metadata={"extra": {"reason": "Ärende KS 2026/123"}},
    )


async def test_log_required_writes_on_the_callers_session_despite_the_configuration():
    repository = AsyncMock()
    written = MagicMock(spec=AuditLog)
    repository.create.return_value = written
    service = _silenced_audit_service(repository)

    with patch("eneo.audit.application.audit_service.job_manager") as job_manager:
        result = await service.log_required(
            **_required_kwargs(ActionType.SPACE_OVERSIGHT_JOINED)
        )

    assert result is written
    repository.create.assert_awaited_once()
    (entry,) = repository.create.await_args.args
    assert entry.action == ActionType.SPACE_OVERSIGHT_JOINED
    assert entry.metadata == {"extra": {"reason": "Ärende KS 2026/123"}}
    # Synchronous insert through the repository, never the ARQ queue.
    job_manager.enqueue.assert_not_called()


async def test_log_required_refuses_an_action_that_is_not_mandatory():
    repository = AsyncMock()
    service = _silenced_audit_service(repository)

    with pytest.raises(ValueError, match="not a mandatory audit action"):
        await service.log_required(
            **_required_kwargs(ActionType.WIDGET_ACTIVATION_REQUESTED)
        )
    repository.create.assert_not_called()


async def test_log_required_fails_when_nothing_was_written():
    service = _silenced_audit_service()
    service.log = AsyncMock(return_value=None)

    with pytest.raises(RuntimeError, match="was not written"):
        await service.log_required(**_required_kwargs(ActionType.WIDGET_PAUSED))


@pytest.mark.parametrize("action", MANDATORY)
async def test_log_async_writes_a_mandatory_action_on_the_session_and_never_queues(
    action,
):
    repository = AsyncMock()
    written = MagicMock(spec=AuditLog)
    written.id = uuid4()
    repository.create.return_value = written
    service = _silenced_audit_service(repository)

    with patch("eneo.audit.application.audit_service.job_manager") as job_manager:
        result = await service.log_async(**_required_kwargs(action))

    assert result == written.id
    repository.create.assert_awaited_once()
    job_manager.enqueue.assert_not_called()


async def test_log_async_lets_a_failed_mandatory_insert_abort_the_change():
    repository = AsyncMock()
    repository.create.side_effect = ConnectionError("database went away")
    service = _silenced_audit_service(repository)

    with patch("eneo.audit.application.audit_service.job_manager") as job_manager:
        with pytest.raises(ConnectionError):
            await service.log_async(**_required_kwargs(ActionType.WIDGET_ARCHIVED))

    job_manager.enqueue.assert_not_called()


async def test_log_async_still_queues_a_configurable_action():
    repository = AsyncMock()
    service = AuditService(repository)

    with patch(
        "eneo.audit.application.audit_service.job_manager",
        new=MagicMock(enqueue=AsyncMock()),
    ) as job_manager:
        await service.log_async(
            **_required_kwargs(ActionType.WIDGET_ACTIVATION_REQUESTED)
        )

    job_manager.enqueue.assert_awaited_once()
    repository.create.assert_not_called()


async def test_log_required_lets_a_failed_insert_abort_the_change():
    repository = AsyncMock()
    repository.create.side_effect = ConnectionError("database went away")
    service = _silenced_audit_service(repository)

    with pytest.raises(ConnectionError):
        await service.log_required(**_required_kwargs(ActionType.WIDGET_ARCHIVED))


@pytest.fixture
def config_repository():
    return AsyncMock()


@pytest.fixture
def config_service(config_repository):
    redis = AsyncMock()
    redis.get.return_value = None
    with patch(
        "eneo.audit.application.audit_config_service.get_redis", return_value=redis
    ):
        return AuditConfigService(config_repository)


async def test_action_config_reports_mandatory_actions_as_locked_on(
    config_service, config_repository
):
    config_repository.find_all_by_tenant.return_value = [
        (
            "admin_actions",
            False,
            {action.value: False for action in MANDATORY_AUDIT_ACTIONS},
        ),
    ]

    result = await config_service.get_action_config(uuid4())

    by_action = {config.action: config for config in result.actions}
    for action in MANDATORY_AUDIT_ACTIONS:
        assert by_action[action].enabled is True
        assert by_action[action].mandatory is True
    assert by_action[ActionType.WIDGET_CREATED].enabled is False
    assert by_action[ActionType.WIDGET_CREATED].mandatory is False
    assert sum(config.mandatory for config in result.actions) == len(
        MANDATORY_AUDIT_ACTIONS
    )


@pytest.mark.parametrize("action", MANDATORY)
async def test_a_mandatory_action_cannot_be_turned_off(
    config_service, config_repository, action
):
    updates = [
        ActionUpdate(action=ActionType.USER_CREATED.value, enabled=False),
        ActionUpdate(action=action.value, enabled=False),
    ]

    with pytest.raises(BadRequestException, match="always logged"):
        await config_service.update_action_config(uuid4(), updates)

    # Refused as a whole: the valid update in the same request is not saved.
    config_repository.update.assert_not_called()


async def test_turning_a_mandatory_action_on_is_harmless(
    config_service, config_repository
):
    config_repository.find_by_tenant_and_category.return_value = None
    config_repository.find_all_by_tenant.return_value = []

    await config_service.update_action_config(
        uuid4(), [ActionUpdate(action=ActionType.WIDGET_PAUSED.value, enabled=True)]
    )

    config_repository.update.assert_awaited_once()


# Routes that write a mandatory entry: the change and its entry commit
# together, before the response says it was made.
MANDATORY_AUDIT_ROUTES = [
    ("POST", "/admin/spaces/{space_id}/members/"),
    ("PATCH", "/admin/spaces/{space_id}/members/{user_id}/"),
    ("DELETE", "/admin/spaces/{space_id}/members/{user_id}/"),
    ("POST", "/admin/spaces/{space_id}/group-members/"),
    ("PATCH", "/admin/spaces/{space_id}/group-members/{group_id}/"),
    ("DELETE", "/admin/spaces/{space_id}/group-members/{group_id}/"),
    ("POST", "/admin/spaces/{space_id}/join/"),
    ("POST", "/admin/spaces/{space_id}/leave/"),
    ("POST", "/user-groups/{id}/"),
    ("POST", "/user-groups/{id}/users/{user_id}/"),
    ("DELETE", "/user-groups/{id}/users/{user_id}/"),
    ("POST", "/widgets/{id}/activation-request/decline/"),
    ("POST", "/widgets/{id}/activate/"),
    ("POST", "/widgets/{id}/pause/"),
    ("POST", "/widgets/{id}/archive/"),
]


def _walk_dependencies(dependant: Dependant) -> Iterator[Dependant]:
    yield dependant
    for child in dependant.dependencies:
        yield from _walk_dependencies(child)


@pytest.mark.parametrize(("method", "path"), MANDATORY_AUDIT_ROUTES)
def test_mandatory_audit_routes_commit_before_the_response(method: str, path: str):
    (route,) = [
        route
        for route in runtime_router_routes()
        if route.path == path and method in (route.methods or set())
    ]
    transactions = [
        dependency
        for dependency in _walk_dependencies(cast(Dependant, route.dependant))
        if dependency.call is get_session_with_transaction
    ]
    assert [dependency.scope for dependency in transactions] == ["function"]
