from uuid import uuid4

import pytest

from intric.main.exceptions import BadRequestException
from intric.personal_chat_policy.domain.personal_chat_policy import (
    PersonalChatPolicy,
    PolicyCompletionModel,
)


def _empty_policy() -> PersonalChatPolicy:
    return PersonalChatPolicy(id=uuid4(), tenant_id=uuid4())


def test_default_policy_has_all_restrictions_disabled():
    p = _empty_policy()
    assert p.models_restriction_enabled is False
    assert p.mcp_restriction_enabled is False
    assert p.prompt_enforcement_enabled is False
    assert p.completion_models == []
    assert p.mcp_server_ids == []
    assert p.default_prompt_library_id is None


def test_set_models_restriction_requires_at_least_one_model_when_enabled():
    p = _empty_policy()
    with pytest.raises(BadRequestException):
        p.set_models_restriction(enabled=True, models=[])


def test_set_models_restriction_rejects_two_defaults():
    p = _empty_policy()
    a = uuid4()
    b = uuid4()
    with pytest.raises(BadRequestException):
        p.set_models_restriction(
            enabled=True,
            models=[
                PolicyCompletionModel(completion_model_id=a, is_default=True),
                PolicyCompletionModel(completion_model_id=b, is_default=True),
            ],
        )


def test_set_models_restriction_rejects_duplicate_model_ids():
    p = _empty_policy()
    a = uuid4()
    with pytest.raises(BadRequestException):
        p.set_models_restriction(
            enabled=True,
            models=[
                PolicyCompletionModel(completion_model_id=a),
                PolicyCompletionModel(completion_model_id=a),
            ],
        )


def test_disabling_models_restriction_clears_models():
    p = _empty_policy()
    a = uuid4()
    p.set_models_restriction(
        enabled=True, models=[PolicyCompletionModel(completion_model_id=a)]
    )
    p.set_models_restriction(enabled=False, models=[])
    assert p.completion_models == []
    assert p.models_restriction_enabled is False


def test_set_mcp_restriction_allows_empty_when_enabled():
    """deny-all is valid (explicit empty whitelist)."""
    p = _empty_policy()
    p.set_mcp_restriction(enabled=True, ids=[])
    assert p.mcp_restriction_enabled is True
    assert p.mcp_server_ids == []


def test_set_mcp_restriction_rejects_duplicates():
    p = _empty_policy()
    a = uuid4()
    with pytest.raises(BadRequestException):
        p.set_mcp_restriction(enabled=True, ids=[a, a])


def test_set_prompt_enforcement_requires_id_when_enabled():
    p = _empty_policy()
    with pytest.raises(BadRequestException):
        p.set_prompt_enforcement(enabled=True, prompt_library_id=None)


def test_disabling_prompt_enforcement_clears_prompt_id():
    p = _empty_policy()
    pid = uuid4()
    p.set_prompt_enforcement(enabled=True, prompt_library_id=pid)
    assert p.default_prompt_library_id == pid
    p.set_prompt_enforcement(enabled=False, prompt_library_id=None)
    assert p.default_prompt_library_id is None
    assert p.prompt_enforcement_enabled is False
