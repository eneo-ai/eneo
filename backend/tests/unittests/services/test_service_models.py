"""Regression tests for ServiceBase.completion_model_kwargs NULL coercion.

Pydantic v2's `default_factory` does not fire for explicit None, so a
`mode="before"` validator is needed to load legacy DB rows where the
JSONB column is NULL. The validator must use `is None` (not truthiness)
so that a future corrupt non-None value still surfaces as ValidationError
rather than being silently turned into an empty ModelKwargs.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from intric.ai_models.completion_models.completion_model import ModelKwargs
from intric.services.service import Service, ServiceBase
from intric.users.user import UserInDBBase


def _user_payload():
    return {
        "id": uuid4(),
        "email": "user@example.com",
        "username": "user",
        "tenant_id": uuid4(),
        "quota_used": 0,
    }


def test_service_base_coerces_db_null_to_default_kwargs():
    """Explicit None must become ModelKwargs() — this is the exact load
    path that crashed personal-space loads when a legacy services row
    had NULL completion_model_kwargs."""
    base = ServiceBase(
        name="s",
        prompt="p",
        completion_model_kwargs=None,
    )

    assert base.completion_model_kwargs == ModelKwargs()


def test_service_base_omitted_kwargs_uses_default_factory():
    """Omitting the field still works via Pydantic's default_factory."""
    base = ServiceBase(name="s", prompt="p")

    assert base.completion_model_kwargs == ModelKwargs()


def test_service_base_preserves_provided_kwargs():
    """Valid input flows through unchanged."""
    base = ServiceBase(
        name="s",
        prompt="p",
        completion_model_kwargs=ModelKwargs(temperature=0.7),
    )

    assert base.completion_model_kwargs is not None
    assert base.completion_model_kwargs.temperature == 0.7


def test_service_base_preserves_dict_kwargs():
    """Dict input (the from_attributes / from-DB shape) parses to ModelKwargs."""
    base = ServiceBase(
        name="s",
        prompt="p",
        completion_model_kwargs={"temperature": 0.5},
    )

    assert base.completion_model_kwargs is not None
    assert base.completion_model_kwargs.temperature == 0.5


@pytest.mark.parametrize("bad_value", [False, "", [], 0])
def test_service_base_rejects_falsy_non_none_values(bad_value):
    """`is None` (not truthiness) so a corrupt False/""/[]/0 still
    raises ValidationError instead of being silently swallowed into an
    empty ModelKwargs — that mask would hide future data corruption."""
    with pytest.raises(ValidationError):
        ServiceBase(
            name="s",
            prompt="p",
            completion_model_kwargs=bad_value,
        )


def test_service_domain_loads_cleanly_with_db_null_kwargs():
    """End-to-end: simulating an ORM row with completion_model_kwargs=None
    feeds through `Service.model_validate(...)` (which BaseRepositoryDelegate
    calls) and yields a clean domain object with default kwargs.

    This is the exact path that was crashing `GET /spaces/type/personal/`."""
    user = UserInDBBase.model_validate(_user_payload())
    service = Service(
        id=uuid4(),
        created_at=None,
        updated_at=None,
        name="legacy_service",
        prompt="p",
        completion_model_kwargs=None,  # the NULL JSONB shape
        user_id=user.id,
        groups=[],
        completion_model_id=uuid4(),
        user=user,
    )

    assert service.completion_model_kwargs == ModelKwargs()
