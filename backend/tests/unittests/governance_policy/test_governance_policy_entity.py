from uuid import uuid4

import pytest

from eneo.governance_policy.domain.governance_policy import (
    GovernancePolicy,
    PolicyCompletionModel,
    PolicyMcpServer,
    PolicyScope,
)
from eneo.main.exceptions import BadRequestException


def _empty_policy() -> GovernancePolicy:
    return GovernancePolicy(
        id=uuid4(), tenant_id=uuid4(), scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT
    )


def test_default_policy_has_all_restrictions_disabled():
    p = _empty_policy()
    assert p.models_restriction_enabled is False
    assert p.mcp_restriction_enabled is False
    assert p.prompt_enforcement_enabled is False
    assert p.completion_models == []
    assert p.mcp_servers == []
    assert p.disabled_mcp_tool_ids == []
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


def test_set_mcp_restriction_rejects_empty_when_enabled():
    """Deny-all is expressed by disabling the dimension, not an empty grant."""
    p = _empty_policy()
    with pytest.raises(BadRequestException):
        p.set_mcp_restriction(enabled=True, servers=[])


def test_set_mcp_restriction_rejects_duplicates():
    p = _empty_policy()
    a = uuid4()
    with pytest.raises(BadRequestException):
        p.set_mcp_restriction(
            enabled=True,
            servers=[
                PolicyMcpServer(mcp_server_id=a),
                PolicyMcpServer(mcp_server_id=a),
            ],
        )


def test_set_mcp_restriction_rejects_duplicate_disabled_tool_ids():
    p = _empty_policy()
    tool = uuid4()
    with pytest.raises(BadRequestException):
        p.set_mcp_restriction(
            enabled=True,
            servers=[PolicyMcpServer(mcp_server_id=uuid4())],
            disabled_tool_ids=[tool, tool],
        )


def test_set_mcp_restriction_stores_default_flag_and_disabled_tools():
    p = _empty_policy()
    server_id = uuid4()
    tool_id = uuid4()
    p.set_mcp_restriction(
        enabled=True,
        servers=[PolicyMcpServer(mcp_server_id=server_id, is_default_enabled=False)],
        disabled_tool_ids=[tool_id],
    )
    assert p.mcp_restriction_enabled is True
    assert p.mcp_servers == [
        PolicyMcpServer(mcp_server_id=server_id, is_default_enabled=False)
    ]
    assert p.disabled_mcp_tool_ids == [tool_id]


def test_disabling_mcp_restriction_clears_servers_and_disabled_tools():
    p = _empty_policy()
    p.set_mcp_restriction(
        enabled=True,
        servers=[PolicyMcpServer(mcp_server_id=uuid4())],
        disabled_tool_ids=[uuid4()],
    )
    p.set_mcp_restriction(enabled=False, servers=[])
    assert p.mcp_restriction_enabled is False
    assert p.mcp_servers == []
    assert p.disabled_mcp_tool_ids == []


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
