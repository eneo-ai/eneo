from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from eneo.roles.permissions import Permission
from eneo.settings.setting_service import SettingService
from eneo.settings.settings import (
    SkillRuntimePolicyPublic,
    SkillRuntimePolicyUpdate,
)
from eneo.skills.domain.skill import SkillRuntimePolicy


def _runtime_policy() -> SkillRuntimePolicy:
    return SkillRuntimePolicy(
        selective_activation_enabled=True,
        max_attached_skills=100,
        context_share_percent=10,
        max_activations_per_turn=5,
    )


def test_public_editable_bounds_match_update_validation_bounds():
    public = SkillRuntimePolicyPublic.from_domain(_runtime_policy())
    update_schema = SkillRuntimePolicyUpdate.model_json_schema()["properties"]

    assert public.editable_bounds.model_dump() == {
        "max_attached_skills": {
            "minimum": update_schema["max_attached_skills"]["minimum"],
            "maximum": update_schema["max_attached_skills"]["maximum"],
        },
        "context_share_percent": {
            "minimum": update_schema["context_share_percent"]["minimum"],
            "maximum": update_schema["context_share_percent"]["maximum"],
        },
        "max_activations_per_turn": {
            "minimum": update_schema["max_activations_per_turn"]["minimum"],
            "maximum": update_schema["max_activations_per_turn"]["maximum"],
        },
    }


def _setting_service() -> SettingService:
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.ADMIN],
    )
    return SettingService(
        repo=MagicMock(),
        user=user,
        ai_models_service=MagicMock(),
        feature_flag_service=MagicMock(),
        tenant_repo=MagicMock(),
        audit_service=MagicMock(),
        skill_repo=MagicMock(),
    )


@pytest.mark.asyncio
async def test_model_projection_uses_canonical_skill_context_allowance():
    service = _setting_service()
    service.skill_repo.get_or_seed_runtime_policy = AsyncMock(
        return_value=_runtime_policy()
    )
    model = SimpleNamespace(
        id=uuid4(),
        name="test-model",
        nickname="Test model",
        max_input_tokens=128_000,
        supports_tool_calling=True,
        can_access=True,
    )
    service.ai_models_service.get_completion_models = AsyncMock(return_value=[model])

    with patch(
        "eneo.settings.setting_service.skill_context_token_allowance",
        return_value=12_345,
    ) as allowance:
        projections = await service.get_skill_runtime_model_projections()

    allowance.assert_called_once_with(
        max_input_tokens=model.max_input_tokens,
        context_share_percent=10,
    )
    assert projections.models[0].skill_context_token_allowance == 12_345
