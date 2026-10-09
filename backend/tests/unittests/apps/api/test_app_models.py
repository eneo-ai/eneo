from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.apps.apps.api.app_models import AppUpdateRequest
from eneo.data_retention.constants import MAX_RETENTION_DAYS, MIN_RETENTION_DAYS
from eneo.main.models import is_provided
from eneo.skills.presentation.skill_models import SkillBindingReferenceInput


def test_app_update_skill_bindings_preserve_patch_semantics():
    omitted = AppUpdateRequest()
    explicit_null = AppUpdateRequest(skill_bindings=None)
    reference = SkillBindingReferenceInput(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
    )
    replacement = AppUpdateRequest(skill_bindings=[reference])
    clear = AppUpdateRequest(skill_bindings=[])

    assert omitted.skill_bindings is None
    assert "skill_bindings" not in omitted.model_fields_set
    assert explicit_null.skill_bindings is None
    assert "skill_bindings" in explicit_null.model_fields_set
    assert replacement.skill_bindings == [reference]
    assert clear.skill_bindings == []


@pytest.mark.parametrize("days", [None, MIN_RETENTION_DAYS, MAX_RETENTION_DAYS])
def test_app_retention_accepts_existing_global_bounds(days: int | None):
    request = AppUpdateRequest(data_retention_days=days)
    assert request.data_retention_days == days
    assert "data_retention_days" in request.model_fields_set


@pytest.mark.parametrize("days", [MIN_RETENTION_DAYS - 1, MAX_RETENTION_DAYS + 1])
def test_app_retention_rejects_values_outside_existing_global_bounds(days: int):
    with pytest.raises(ValidationError):
        AppUpdateRequest(data_retention_days=days)


def test_app_retention_omitted_does_not_clear_override():
    assert not is_provided(AppUpdateRequest().data_retention_days)
