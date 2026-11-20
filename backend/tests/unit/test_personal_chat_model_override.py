from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.assistants.assistant_service import AssistantService
from eneo.main.exceptions import BadRequestException


def test_personal_chat_model_selection_respects_space_and_policy():
    assistant = SimpleNamespace(id=uuid4())
    allowed = SimpleNamespace(id=uuid4())
    other = SimpleNamespace(id=uuid4())
    available = {allowed.id: allowed, other.id: other}
    space = SimpleNamespace(
        is_personal=lambda: True,
        default_assistant=assistant,
        is_completion_model_available=lambda model_id: model_id in available,
        get_completion_model=lambda model_id: available[model_id],
        validate_model_security_compatibility=lambda _model: None,
    )
    policy = SimpleNamespace(models_enforced=True, available_models=[allowed])

    assert (
        AssistantService.resolve_personal_chat_model_override(
            space=space,
            assistant=assistant,
            effective_config=policy,
            completion_model_id=allowed.id,
        )
        is allowed
    )

    with pytest.raises(BadRequestException, match="policy"):
        AssistantService.resolve_personal_chat_model_override(
            space=space,
            assistant=assistant,
            effective_config=policy,
            completion_model_id=other.id,
        )

    with pytest.raises(BadRequestException, match="no longer available"):
        AssistantService.resolve_personal_chat_model_override(
            space=space,
            assistant=assistant,
            effective_config=policy,
            completion_model_id=uuid4(),
        )


def test_model_selection_only_applies_to_personal_default_assistant():
    assistant = SimpleNamespace(id=uuid4())
    model = SimpleNamespace(id=uuid4())
    space = SimpleNamespace(is_personal=lambda: True, default_assistant=assistant)

    with pytest.raises(BadRequestException, match="personal chat"):
        AssistantService.resolve_personal_chat_model_override(
            space=space,
            assistant=SimpleNamespace(id=uuid4()),
            effective_config=None,
            completion_model_id=model.id,
        )

    space.is_personal = lambda: False
    with pytest.raises(BadRequestException, match="personal chat"):
        AssistantService.resolve_personal_chat_model_override(
            space=space,
            assistant=assistant,
            effective_config=None,
            completion_model_id=model.id,
        )
