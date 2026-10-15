"""The reader model for a space or a turn: the personal-space policy first,
then the space's own choice, then the organisation default, and each of them
only when it clears the same bars as the turn's model."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.governance_policy.domain.policy_resolver import (
    EffectiveConfig,
    resolve_reader_model,
)


def _model(*, level=2, tools=True):
    def meets(classification):
        return classification is None or level >= classification.security_level

    return SimpleNamespace(
        id=uuid4(),
        is_org_reader=False,
        supports_tool_calling=tools,
        meets_security_classification=meets,
    )


def _floor(level):
    return SimpleNamespace(security_level=level)


def _config(**overrides) -> EffectiveConfig:
    base = EffectiveConfig(
        models_enforced=False,
        available_models=[],
        locked_model=None,
        policy_default_model=None,
        mcp_enforced=False,
        available_mcp_servers=[],
        prompt_enforced=False,
        enforced_prompt_text=None,
    )
    return replace(base, **overrides)


def _resolve(
    *,
    personal=False,
    space_models=None,
    inherit=True,
    own=None,
    floor=None,
    tenant_default=None,
    config=None,
    turn=None,
):
    return resolve_reader_model(
        space_is_personal=personal,
        space_completion_models=space_models
        if space_models is not None
        else [_model()],
        space_reader_inherit=inherit,
        space_reader_model=own,
        space_security_classification=floor,
        tenant_default=tenant_default,
        effective_config=config,
        turn_model_id=turn.id if turn else None,
    )


class TestOrganisationDefault:
    def test_is_inherited_when_it_meets_the_space(self):
        default = _model(level=2)

        result = _resolve(tenant_default=default, floor=_floor(2))

        assert (result.model, result.reason) == (default, "inherited")

    def test_is_refused_below_the_space_classification(self):
        default = _model(level=1)

        result = _resolve(tenant_default=default, floor=_floor(2))

        assert (result.model, result.reason) == (
            None,
            "tenant_default_below_classification",
        )

    def test_nothing_without_one(self):
        result = _resolve(tenant_default=None)

        assert (result.model, result.reason) == (None, "no_tenant_default")

    def test_the_turn_model_is_never_its_own_reader(self):
        default = _model()

        result = _resolve(tenant_default=default, turn=default)

        assert (result.model, result.reason) == (None, "same_as_turn")


class TestSpaceChoice:
    def test_own_choice_replaces_the_default(self):
        own, default = _model(), _model()

        result = _resolve(inherit=False, own=own, tenant_default=default)

        assert (result.model, result.reason) == (own, "own")

    def test_explicit_none_means_none_even_with_a_default(self):
        result = _resolve(inherit=False, own=None, tenant_default=_model())

        assert (result.model, result.reason) == (None, "none")

    def test_own_choice_below_a_raised_classification_is_dropped(self):
        own = _model(level=1)

        result = _resolve(inherit=False, own=own, floor=_floor(3))

        assert (result.model, result.reason) == (None, "own_below_classification")

    def test_no_tool_capable_model_means_no_digest_and_no_reader(self):
        result = _resolve(space_models=[_model(tools=False)], tenant_default=_model())

        assert (result.model, result.reason) == (None, "no_tool_capable_model")

    def test_personal_spaces_skip_the_tool_check(self):
        default = _model()

        result = _resolve(personal=True, space_models=[], tenant_default=default)

        assert result.model is default


class TestPersonalSpacePolicy:
    def test_policy_choice_wins_over_the_default(self):
        chosen, default = _model(), _model()
        config = _config(
            reader_governed=True, reader_model_inherit=False, reader_model=chosen
        )

        result = _resolve(personal=True, tenant_default=default, config=config)

        assert (result.model, result.reason) == (chosen, "policy")

    def test_policy_none_means_none(self):
        config = _config(
            reader_governed=True, reader_model_inherit=False, reader_model=None
        )

        result = _resolve(personal=True, tenant_default=_model(), config=config)

        assert (result.model, result.reason) == (None, "none")

    def test_policy_inherit_falls_back_to_the_default(self):
        default = _model()
        config = _config(reader_governed=True, reader_model_inherit=True)

        result = _resolve(personal=True, tenant_default=default, config=config)

        assert (result.model, result.reason) == (default, "inherited")

    @pytest.mark.parametrize("pinned", [False, True])
    def test_an_enforced_models_policy_must_allow_the_reader(self, pinned):
        default, other = _model(), _model()
        allowed = [other] if pinned else [other, default]
        config = _config(
            models_enforced=True,
            available_models=allowed,
            locked_model=other if pinned else None,
        )

        result = _resolve(personal=True, tenant_default=default, config=config)

        if pinned:
            assert (result.model, result.reason) == (None, "policy_disallows")
        else:
            assert result.model is default
