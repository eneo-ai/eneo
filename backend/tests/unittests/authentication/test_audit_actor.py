"""Who an audit entry names as its actor, for the principals that have no users row."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from eneo.audit.application.audit_service import AuditService
from eneo.audit.application.audit_task_params import AuditLogTaskParams
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_models import ApiKeyOwnership, audit_actor_for
from eneo.widgets.domain.visitor import WidgetVisitorContext


def test_a_signed_in_user_is_the_actor_of_its_entries():
    user = SimpleNamespace(id=uuid4(), active_api_key=None, active_widget=None)
    assert audit_actor_for(user) == (user.id, ActorType.USER)  # type: ignore[arg-type]


def test_a_service_key_is_its_own_kind_of_actor_without_a_row():
    # The audit service names the key through actor_api_key_id instead.
    user = SimpleNamespace(
        id=uuid4(),
        active_api_key=SimpleNamespace(ownership=ApiKeyOwnership.SERVICE),
        active_widget=None,
    )
    assert audit_actor_for(user) == (None, ActorType.API_KEY)  # type: ignore[arg-type]


def test_a_widget_visitor_is_its_own_kind_of_actor_without_a_row():
    # The synthetic visitor's id is a pseudonymous visitor id: never a users.id,
    # so it must not reach audit_log.actor_id (a foreign key to users).
    context = WidgetVisitorContext(
        widget_id=uuid4(),
        visitor_id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        target_id=uuid4(),
        token_generation=0,
    )
    visitor = SimpleNamespace(id=uuid4(), active_api_key=None, active_widget=context)
    assert audit_actor_for(visitor) == (None, ActorType.WIDGET_VISITOR)  # type: ignore[arg-type]


def test_a_user_double_with_a_truthy_attribute_is_still_a_user():
    # Test doubles answer every attribute with something truthy; only the real
    # visitor context makes an actorless entry.
    double = SimpleNamespace(id=uuid4(), active_api_key=None, active_widget=object())
    assert audit_actor_for(double) == (double.id, ActorType.USER)  # type: ignore[arg-type]


def _params(**overrides) -> AuditLogTaskParams:
    values = dict(
        tenant_id=uuid4(),
        actor_id=None,
        actor_type=ActorType.WIDGET_VISITOR,
        action=ActionType.WIDGET_EXTERNAL_TOOL_CALLED,
        entity_type=EntityType.WIDGET,
        entity_id=uuid4(),
        description="Widget 'w': an anonymous visitor's turn ran a tool",
    )
    values.update(overrides)
    return AuditLogTaskParams(**values)


def test_the_queued_entry_accepts_an_actorless_visitor_but_not_an_actorless_user():
    assert _params().actor_id is None
    assert _params(actor_type=ActorType.SYSTEM).actor_id is None
    with pytest.raises(ValueError, match="actor_id required"):
        _params(actor_type=ActorType.USER)


def test_the_queued_entry_names_a_service_key_by_its_key_id():
    key_id = uuid4()
    params = _params(actor_type=ActorType.API_KEY, actor_api_key_id=key_id)
    assert (params.actor_id, params.actor_api_key_id) == (None, key_id)
    with pytest.raises(ValueError, match="actor_api_key_id required"):
        _params(actor_type=ActorType.API_KEY)


async def _write(log: str, **actor) -> tuple[str, str | None]:
    """Write one entry with ``log`` or ``log_async`` and return the actor
    type and actor id of what was written: the row given to the repository,
    or the params put on the queue. Exactly one write is expected."""
    repository = AsyncMock()
    with patch("eneo.audit.application.audit_service.job_manager") as job_manager:
        job_manager.enqueue = AsyncMock()
        await getattr(AuditService(repository), log)(
            tenant_id=uuid4(),
            action=ActionType.WIDGET_EXTERNAL_TOOL_CALLED,
            entity_type=EntityType.WIDGET,
            entity_id=uuid4(),
            description="Widget 'w': an anonymous visitor's turn ran a tool",
            metadata={},
            **actor,
        )
    if log == "log":
        (created,) = repository.create.await_args_list
        row = created.args[0]
        return row.actor_type.value, row.actor_id
    (enqueued,) = job_manager.enqueue.await_args_list
    params = enqueued.args[2]
    return params["actor_type"], params["actor_id"]


@pytest.mark.parametrize("log", ["log", "log_async"])
@pytest.mark.parametrize(
    ("actor_type", "refusal"),
    [
        (ActorType.WIDGET_VISITOR, None),
        (ActorType.USER, "actor_id required"),
        (ActorType.API_KEY, "actor_api_key_id required"),
    ],
)
async def test_both_writers_accept_an_actorless_visitor_and_refuse_an_unnamed_actor(
    log, actor_type, refusal
):
    if refusal is None:
        assert await _write(log, actor_type=actor_type, actor_id=None) == (
            "widget_visitor",
            None,
        )
    else:
        with pytest.raises(ValueError, match=refusal):
            await _write(log, actor_type=actor_type, actor_id=None)


def test_only_system_visitor_and_service_key_entries_go_without_an_actor_row():
    assert {actor for actor in ActorType if not actor.requires_actor_id} == {
        ActorType.SYSTEM,
        ActorType.WIDGET_VISITOR,
        ActorType.API_KEY,
    }
