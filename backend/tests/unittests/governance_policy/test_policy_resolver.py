from types import SimpleNamespace
from uuid import uuid4

from intric.governance_policy.domain.governance_policy import (
    GovernancePolicy,
    PolicyCompletionModel,
    PolicyMcpServer,
    PolicyScope,
)
from intric.governance_policy.domain.policy_resolver import (
    EffectiveConfig,
    resolve,
    select_effective_completion_model,
)


def _mk_assistant(is_default: bool = True):
    return SimpleNamespace(is_default=is_default)


def _mk_model(id=None, name="m", provider_id=None):
    return SimpleNamespace(id=id or uuid4(), name=name, provider_id=provider_id)


def _mk_mcp(id=None, name="s", tools=None):
    return SimpleNamespace(id=id or uuid4(), name=name, tools=tools or [])


def _mk_tool(id=None, name="t"):
    return SimpleNamespace(id=id or uuid4(), name=name)


def _empty_policy() -> GovernancePolicy:
    return GovernancePolicy(
        id=uuid4(), tenant_id=uuid4(), scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT
    )


def test_non_default_assistant_returns_all_disabled():
    cfg = resolve(
        assistant=_mk_assistant(is_default=False),
        space_is_personal=True,
        policy=_empty_policy(),
        tenant_completion_models=[],
        tenant_mcp_servers=[],
        library_prompt_text="x",
    )
    assert cfg.models_enforced is False
    assert cfg.mcp_enforced is False
    assert cfg.prompt_enforced is False
    assert cfg.enforced_prompt_text is None


def test_non_personal_space_returns_all_disabled():
    policy = _empty_policy()
    policy.set_models_restriction(
        enabled=True, models=[PolicyCompletionModel(completion_model_id=uuid4())]
    )
    cfg = resolve(
        assistant=_mk_assistant(is_default=True),
        space_is_personal=False,
        policy=policy,
        tenant_completion_models=[_mk_model()],
        tenant_mcp_servers=[],
        library_prompt_text="x",
    )
    assert cfg.models_enforced is False
    assert cfg.mcp_enforced is False
    assert cfg.prompt_enforced is False


def test_no_policy_returns_all_disabled():
    cfg = resolve(
        assistant=_mk_assistant(),
        space_is_personal=True,
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
        space_is_personal=True,
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
        space_is_personal=True,
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
        space_is_personal=True,
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
        space_is_personal=True,
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
        space_is_personal=True,
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
        space_is_personal=True,
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
        space_is_personal=True,
        policy=p,
        tenant_completion_models=[],
        tenant_mcp_servers=[s],
        library_prompt_text=None,
    )
    assert cfg.mcp_enforced is False
    assert cfg.available_mcp_servers == []


def test_mcp_enabled_with_stale_empty_whitelist_is_deny_all():
    """The entity rejects enabled+empty, but a stale persisted state must
    still resolve to deny-all rather than crash or grant everything."""
    s = _mk_mcp()
    p = _empty_policy()
    p.mcp_restriction_enabled = True
    cfg = resolve(
        assistant=_mk_assistant(),
        space_is_personal=True,
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
    p.set_mcp_restriction(
        enabled=True,
        servers=[
            PolicyMcpServer(mcp_server_id=s1.id),
            PolicyMcpServer(mcp_server_id=stale_id),
        ],
    )
    cfg = resolve(
        assistant=_mk_assistant(),
        space_is_personal=True,
        policy=p,
        tenant_completion_models=[],
        tenant_mcp_servers=[s1, s2],
        library_prompt_text=None,
    )
    assert cfg.available_mcp_servers == [s1]
    assert cfg.default_disabled_mcp_server_ids == []


def test_mcp_disabled_tools_are_filtered_out_without_mutating_entity():
    kept, dropped = _mk_tool(), _mk_tool()
    s = _mk_mcp(tools=[kept, dropped])
    p = _empty_policy()
    p.set_mcp_restriction(
        enabled=True,
        servers=[PolicyMcpServer(mcp_server_id=s.id)],
        disabled_tool_ids=[dropped.id],
    )
    cfg = resolve(
        assistant=_mk_assistant(),
        space_is_personal=True,
        policy=p,
        tenant_completion_models=[],
        tenant_mcp_servers=[s],
        library_prompt_text=None,
    )
    (resolved,) = cfg.available_mcp_servers
    assert [t.id for t in resolved.tools] == [kept.id]
    # The tenant entity is shared with other readers — must stay untouched.
    assert [t.id for t in s.tools] == [kept.id, dropped.id]


def test_mcp_server_without_disabled_tools_is_passed_through_unchanged():
    s = _mk_mcp(tools=[_mk_tool()])
    other_server_tool = uuid4()
    p = _empty_policy()
    p.set_mcp_restriction(
        enabled=True,
        servers=[PolicyMcpServer(mcp_server_id=s.id)],
        disabled_tool_ids=[other_server_tool],
    )
    cfg = resolve(
        assistant=_mk_assistant(),
        space_is_personal=True,
        policy=p,
        tenant_completion_models=[],
        tenant_mcp_servers=[s],
        library_prompt_text=None,
    )
    assert cfg.available_mcp_servers == [s]


def test_mcp_default_disabled_servers_are_reported():
    s1, s2 = _mk_mcp(), _mk_mcp()
    stale_id = uuid4()
    p = _empty_policy()
    p.set_mcp_restriction(
        enabled=True,
        servers=[
            PolicyMcpServer(mcp_server_id=s1.id, is_default_enabled=False),
            PolicyMcpServer(mcp_server_id=s2.id, is_default_enabled=True),
            PolicyMcpServer(mcp_server_id=stale_id, is_default_enabled=False),
        ],
    )
    cfg = resolve(
        assistant=_mk_assistant(),
        space_is_personal=True,
        policy=p,
        tenant_completion_models=[],
        tenant_mcp_servers=[s1, s2],
        library_prompt_text=None,
    )
    # Stale server ids never reach the frontend seed list.
    assert cfg.default_disabled_mcp_server_ids == [s1.id]


def test_prompt_disabled_returns_none():
    p = _empty_policy()
    cfg = resolve(
        assistant=_mk_assistant(),
        space_is_personal=True,
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
        space_is_personal=True,
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
        space_is_personal=True,
        policy=p,
        tenant_completion_models=[],
        tenant_mcp_servers=[],
        library_prompt_text=None,
    )
    assert cfg.prompt_enforced is True
    assert cfg.enforced_prompt_text is None


# ---- select_effective_completion_model ----------------------------------


def _eff_config(
    *,
    models_enforced=True,
    available_models=None,
    policy_default_model=None,
) -> EffectiveConfig:
    return EffectiveConfig(
        models_enforced=models_enforced,
        available_models=available_models or [],
        locked_model=None,
        policy_default_model=policy_default_model,
        mcp_enforced=False,
        available_mcp_servers=[],
        prompt_enforced=False,
        enforced_prompt_text=None,
    )


def test_select_model_no_config_returns_current():
    current = _mk_model()
    assert select_effective_completion_model(current, None) is current


def test_select_model_not_enforced_returns_current():
    current = _mk_model()
    cfg = _eff_config(models_enforced=False, available_models=[_mk_model()])
    assert select_effective_completion_model(current, cfg) is current


def test_select_model_enforced_and_allowed_keeps_current():
    current = _mk_model()
    cfg = _eff_config(available_models=[current, _mk_model()])
    assert select_effective_completion_model(current, cfg) is current


def test_select_model_disallowed_falls_back_to_policy_default():
    current = _mk_model()
    allowed, default = _mk_model(), _mk_model()
    cfg = _eff_config(available_models=[allowed, default], policy_default_model=default)
    assert select_effective_completion_model(current, cfg) is default


def test_select_model_disallowed_no_default_falls_back_to_first_allowed():
    current = _mk_model()
    first, second = _mk_model(), _mk_model()
    cfg = _eff_config(available_models=[first, second])
    assert select_effective_completion_model(current, cfg) is first


def test_select_model_none_current_falls_back_to_allowed():
    first = _mk_model()
    cfg = _eff_config(available_models=[first])
    assert select_effective_completion_model(None, cfg) is first


def test_select_model_enforced_empty_whitelist_returns_none():
    cfg = _eff_config(available_models=[])
    assert select_effective_completion_model(_mk_model(), cfg) is None
