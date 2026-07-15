from uuid import uuid4

from eneo.apps.apps.api.app_models import AppUpdateRequest
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
