from types import SimpleNamespace
from uuid import uuid4

from intric.personal_assistant_policy.domain.personal_assistant_policy import (
    PersonalAssistantPolicy,
    PolicyCompletionModel,
)
from intric.personal_assistant_policy.domain.policy_resolver import resolve


def _mk_assistant(is_default: bool = True):
    return SimpleNamespace(is_default=is_default)


def _mk_model(id=None, name="m", provider_id=None):
    return SimpleNamespace(id=id or uuid4(), name=name, provider_id=provider_id)


def _mk_mcp(id=None, name="s"):
    return SimpleNamespace(id=id or uuid4(), name=name)


def _empty_policy() -> PersonalAssistantPolicy:
    return PersonalAssistantPolicy(id=uuid4(), tenant_id=uuid4())


def test_non_default_assistant_returns_all_disabled():
    cfg = resolve(
        assistant=_mk_assistant(is_default=False),
        policy=_empty_policy(),
        tenant_completion_models=[],
        tenant_mcp_servers=[],
        library_prompt_text="x",
    )
    assert cfg.models_enforced is False
    assert cfg.mcp_enforced is False
    assert cfg.prompt_enforced is False
    assert cfg.enforced_prompt_text is None


def test_no_policy_returns_all_disabled():
    cfg = resolve(
        assistant=_mk_assistant(),
        policy=None,
        tenant_completion_models=[_mk_model()],
        tenant_mcp_servers=[_mk_mcp()],
        library_prompt_text="x",
    )
    assert cfg.models_enforced is False
    assert cfg.mcp_enforced is False
    assert cfg.prompt_enforced is False


def test_models_disabled_means_no_filtering_even_with_m2m_rows():
    p = _empty_policy()
    p.set_models_restriction(
        enabled=True, models=[PolicyCompletionModel(completion_model_id=uuid4())]
    )
    p.models_restriction_enabled = False
    cfg = resolve(
        assistant=_mk_assistant(),
        policy=p,
        tenant_completion_models=[_mk_model()],
        tenant_mcp_servers=[],
        library_prompt_text=None,
    )
    assert cfg.models_enforced is False
    assert cfg.available_models == []
    assert cfg.locked_model is None


def test_models_enforced_with_single_model_locks():
    m = _mk_model()
    p = _empty_policy()
    p.set_models_restriction(
        enabled=True,
        models=[PolicyCompletionModel(completion_model_id=m.id)],
    )
    cfg = resolve(
        assistant=_mk_assistant(),
        policy=p,
        tenant_completion_models=[m, _mk_model()],
        tenant_mcp_servers=[],
        library_prompt_text=None,
    )
    assert cfg.models_enforced is True
    assert cfg.locked_model is m
    assert cfg.available_models == [m]


def test_models_enforced_with_multiple_models_no_lock():
    m1, m2 = _mk_model(), _mk_model()
    p = _empty_policy()
    p.set_models_restriction(
        enabled=True,
        models=[
            PolicyCompletionModel(completion_model_id=m1.id),
            PolicyCompletionModel(completion_model_id=m2.id),
        ],
    )
    cfg = resolve(
        assistant=_mk_assistant(),
        policy=p,
        tenant_completion_models=[m1, m2, _mk_model()],
        tenant_mcp_servers=[],
        library_prompt_text=None,
    )
    assert cfg.locked_model is None
    assert {m.id for m in cfg.available_models} == {m1.id, m2.id}


def test_stale_model_in_policy_not_in_tenant_list_is_filtered_out():
    m1 = _mk_model()
    stale_id = uuid4()
    p = _empty_policy()
    p.set_models_restriction(
        enabled=True,
        models=[
            PolicyCompletionModel(completion_model_id=m1.id),
            PolicyCompletionModel(completion_model_id=stale_id),
        ],
    )
    cfg = resolve(
        assistant=_mk_assistant(),
        policy=p,
        tenant_completion_models=[m1],
        tenant_mcp_servers=[],
        library_prompt_text=None,
    )
    # Only m1 survives; stale_id filtered. Since only m1 remains it's locked.
    assert cfg.available_models == [m1]
    assert cfg.locked_model is m1


def test_policy_default_model_is_set_when_one_flagged():
    m1, m2 = _mk_model(), _mk_model()
    p = _empty_policy()
    p.set_models_restriction(
        enabled=True,
        models=[
            PolicyCompletionModel(completion_model_id=m1.id, is_default=False),
            PolicyCompletionModel(completion_model_id=m2.id, is_default=True),
        ],
    )
    cfg = resolve(
        assistant=_mk_assistant(),
        policy=p,
        tenant_completion_models=[m1, m2],
        tenant_mcp_servers=[],
        library_prompt_text=None,
    )
    assert cfg.policy_default_model is m2


def test_policy_default_model_none_when_no_default_flagged():
    m1 = _mk_model()
    p = _empty_policy()
    p.set_models_restriction(
        enabled=True,
        models=[PolicyCompletionModel(completion_model_id=m1.id)],
    )
    cfg = resolve(
        assistant=_mk_assistant(),
        policy=p,
        tenant_completion_models=[m1],
        tenant_mcp_servers=[],
        library_prompt_text=None,
    )
    assert cfg.policy_default_model is None


def test_mcp_disabled_no_filtering():
    s = _mk_mcp()
    p = _empty_policy()
    cfg = resolve(
        assistant=_mk_assistant(),
        policy=p,
        tenant_completion_models=[],
        tenant_mcp_servers=[s],
        library_prompt_text=None,
    )
    assert cfg.mcp_enforced is False
    assert cfg.available_mcp_servers == []


def test_mcp_enabled_with_empty_whitelist_is_deny_all():
    s = _mk_mcp()
    p = _empty_policy()
    p.set_mcp_restriction(enabled=True, ids=[])
    cfg = resolve(
        assistant=_mk_assistant(),
        policy=p,
        tenant_completion_models=[],
        tenant_mcp_servers=[s],
        library_prompt_text=None,
    )
    assert cfg.mcp_enforced is True
    assert cfg.available_mcp_servers == []


def test_mcp_enforced_filters_to_whitelist_intersection_with_tenant():
    s1, s2 = _mk_mcp(), _mk_mcp()
    stale_id = uuid4()
    p = _empty_policy()
    p.set_mcp_restriction(enabled=True, ids=[s1.id, stale_id])
    cfg = resolve(
        assistant=_mk_assistant(),
        policy=p,
        tenant_completion_models=[],
        tenant_mcp_servers=[s1, s2],
        library_prompt_text=None,
    )
    assert cfg.available_mcp_servers == [s1]


def test_prompt_disabled_returns_none():
    p = _empty_policy()
    cfg = resolve(
        assistant=_mk_assistant(),
        policy=p,
        tenant_completion_models=[],
        tenant_mcp_servers=[],
        library_prompt_text="ignored",
    )
    assert cfg.prompt_enforced is False
    assert cfg.enforced_prompt_text is None


def test_prompt_enforced_with_text_returns_text():
    p = _empty_policy()
    pid = uuid4()
    p.set_prompt_enforcement(enabled=True, prompt_library_id=pid)
    cfg = resolve(
        assistant=_mk_assistant(),
        policy=p,
        tenant_completion_models=[],
        tenant_mcp_servers=[],
        library_prompt_text="be helpful",
    )
    assert cfg.prompt_enforced is True
    assert cfg.enforced_prompt_text == "be helpful"


def test_prompt_enforced_without_text_fails_safe():
    """Service should prevent this state, but resolver must not crash if it
    happens (stale state)."""
    p = _empty_policy()
    p.set_prompt_enforcement(enabled=True, prompt_library_id=uuid4())
    cfg = resolve(
        assistant=_mk_assistant(),
        policy=p,
        tenant_completion_models=[],
        tenant_mcp_servers=[],
        library_prompt_text=None,
    )
    assert cfg.prompt_enforced is True
    assert cfg.enforced_prompt_text is None
