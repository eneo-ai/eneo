from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.authentication.principal import Principal
from eneo.authentication.principal_types import PrincipalType


def _service_key_user(service_principal_id):
    """The made-up user a service key signs in as: its id is the key's id."""
    key = SimpleNamespace(
        id=uuid4(), ownership="service", service_principal_id=service_principal_id
    )
    return SimpleNamespace(id=key.id, active_api_key=key)


def test_a_signed_in_person_is_recorded_as_the_creator():
    user = SimpleNamespace(id=uuid4(), active_api_key=None)

    principal = Principal.from_user(user)

    assert not principal.is_service_key
    assert principal.creator_columns() == {
        "user_id": user.id,
        "created_by_service_id": None,
    }


def test_a_personal_key_acts_as_its_owner():
    owner_id = uuid4()
    key = SimpleNamespace(id=uuid4(), ownership="user", service_principal_id=None)

    principal = Principal.from_user(SimpleNamespace(id=owner_id, active_api_key=key))

    assert principal.principal_type is PrincipalType.USER
    assert principal.creator_columns()["user_id"] == owner_id


def test_a_service_key_is_recorded_as_its_principal_never_as_a_user():
    principal_id = uuid4()
    user = _service_key_user(principal_id)

    principal = Principal.from_user(user)

    assert principal.is_service_key
    assert principal.actor_api_key_id == user.active_api_key.id
    assert principal.creator_columns() == {
        "user_id": None,
        "created_by_service_id": principal_id,
    }


def test_a_rotated_service_key_is_the_same_creator():
    principal_id = uuid4()

    before = Principal.from_user(_service_key_user(principal_id)).creator_columns()
    after = Principal.from_user(_service_key_user(principal_id)).creator_columns()

    assert before == after


def test_a_service_key_without_a_principal_is_nobody():
    with pytest.raises(ValueError):
        Principal.from_user(_service_key_user(None))


def test_a_user_without_the_key_field_is_a_person():
    """Stored user records carry no request-scoped key."""
    user = SimpleNamespace(id=uuid4())

    assert Principal.from_user(user).creator_columns()["user_id"] == user.id
