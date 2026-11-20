"""Who an audit entry names as its actor, for the principals that have no users row."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.audit.application.audit_task_params import AuditLogTaskParams
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_models import ApiKeyOwnership, audit_actor_for
from eneo.widgets.domain.visitor import WidgetVisitorContext


def test_a_signed_in_user_is_the_actor_of_its_entries():
    user = SimpleNamespace(id=uuid4(), active_api_key=None, active_widget=None)
    assert audit_actor_for(user) == (user.id, ActorType.USER)  # type: ignore[arg-type]


def test_a_service_key_has_no_actor_row():
    user = SimpleNamespace(
        id=uuid4(),
        active_api_key=SimpleNamespace(ownership=ApiKeyOwnership.SERVICE),
        active_widget=None,
    )
    assert audit_actor_for(user) == (None, ActorType.SYSTEM)  # type: ignore[arg-type]


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
    with pytest.raises(ValueError, match="actor_id required"):
        _params(actor_type=ActorType.API_KEY)


def test_only_system_and_visitor_entries_go_without_an_actor_row():
    assert {actor for actor in ActorType if not actor.requires_actor_id} == {
        ActorType.SYSTEM,
        ActorType.WIDGET_VISITOR,
    }
