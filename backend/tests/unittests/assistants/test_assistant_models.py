"""Regression tests for AssistantBase.completion_model_kwargs NULL coercion.

Mirrors the equivalent `services` tests so the two peer domains enforce
the same invariant: explicit None coerces to `ModelKwargs()`, but a
corrupt non-None falsy value (False, "", [], 0) still raises
ValidationError instead of being silently turned into an empty
ModelKwargs.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.api.assistant_models import AssistantBase, AssistantUpdatePublic
from eneo.skills.presentation.skill_models import SkillBindingReferenceInput


def test_assistant_base_coerces_db_null_to_default_kwargs():
    base = AssistantBase(name="a", completion_model_kwargs=None)

    assert base.completion_model_kwargs == ModelKwargs()


def test_assistant_base_omitted_kwargs_uses_default_factory():
    base = AssistantBase(name="a")

    assert base.completion_model_kwargs == ModelKwargs()


def test_assistant_base_preserves_provided_kwargs():
    base = AssistantBase(name="a", completion_model_kwargs=ModelKwargs(temperature=0.7))

    assert base.completion_model_kwargs is not None
    assert base.completion_model_kwargs.temperature == 0.7


@pytest.mark.parametrize("bad_value", [False, "", [], 0])
def test_assistant_base_rejects_falsy_non_none_values(bad_value):
    """Only None is coerced; everything else flows through Pydantic, so a
    corrupt falsy value still raises rather than silently becoming `{}`."""
    with pytest.raises(ValidationError):
        AssistantBase(name="a", completion_model_kwargs=bad_value)


def test_assistant_update_skill_bindings_preserve_patch_semantics():
    omitted = AssistantUpdatePublic()
    explicit_null = AssistantUpdatePublic(skill_bindings=None)
    reference = SkillBindingReferenceInput(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
    )
    replacement = AssistantUpdatePublic(skill_bindings=[reference])
    clear = AssistantUpdatePublic(skill_bindings=[])

    assert omitted.skill_bindings is None
    assert "skill_bindings" not in omitted.model_fields_set
    assert explicit_null.skill_bindings is None
    assert "skill_bindings" in explicit_null.model_fields_set
    assert replacement.skill_bindings == [reference]
    assert clear.skill_bindings == []
