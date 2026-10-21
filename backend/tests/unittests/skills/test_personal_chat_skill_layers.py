"""The personal layer of the personal chat runs exactly as configured, or not
at all, and never weakens the organisation layer
(docs/adr/personal-chat-skill-layers.md, section 5)."""

from uuid import uuid4

import pytest

from eneo.completion_models.domain.skill_activation import (
    SkillActivationFallbackReason,
    SkillActivationRejectionReason,
)
from eneo.skills.domain.personal_chat_skill_layers import (
    PersonalSkillLayerDecision,
    PersonalSkillLayerReason,
    PersonalSkillLayerSave,
    PersonalSkillLayerStatus,
    assert_personal_skill_layer_save,
    assess_personal_skill_layer,
    compose_layers,
)
from eneo.skills.domain.skill import (
    PersonalSkillLayerRejectedError,
    ResolvedSkillBinding,
    SkillActivationMode,
    SkillBindingSource,
    SkillRuntimePolicy,
    SkillRuntimeResolution,
)

ALWAYS = SkillActivationMode.ALWAYS
ON_DEMAND = SkillActivationMode.ON_DEMAND


def _binding(
    name: str,
    *,
    position: int,
    mode: SkillActivationMode = ALWAYS,
    instructions: str = "Follow the short guidance.",
    description: str = "Short guidance",
    source: SkillBindingSource = SkillBindingSource.SPACE,
) -> ResolvedSkillBinding:
    return ResolvedSkillBinding(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
        current_revision_id=uuid4(),
        skill_space_id=uuid4(),
        slug=name.lower().replace(" ", "-"),
        revision_number=1,
        current_revision_number=1,
        display_name=name,
        description=description,
        instructions=instructions,
        content_digest="a" * 64,
        position=position,
        source=source,
        activation_mode=mode,
    )


def _policy(**overrides) -> SkillRuntimePolicy:
    values = {
        "selective_activation_enabled": True,
        "max_attached_skills": 100,
        "context_share_percent": 10,
        "max_activations_per_turn": 10,
    }
    values.update(overrides)
    return SkillRuntimePolicy(**values)


def _resolution(*bindings, blocked=()) -> SkillRuntimeResolution:
    return SkillRuntimeResolution(eligible=tuple(bindings), blocked=tuple(blocked))


def _assess(
    *,
    organisation=_resolution(),
    personal=_resolution(),
    holds_permission=True,
    policy=None,
    max_input_tokens=128_000,
    supports_tool_calling=True,
):
    return assess_personal_skill_layer(
        base_instructions="Base",
        organisation=organisation,
        personal=personal,
        policy=policy or _policy(),
        holds_permission=holds_permission,
        model_route="openai/gpt-4o",
        max_input_tokens=max_input_tokens,
        supports_tool_calling=supports_tool_calling,
        prompt_files=(),
    )


def test_no_personal_bindings_is_empty():
    decision = _assess(organisation=_resolution(_binding("Klarspråk", position=0)))

    assert decision.status is PersonalSkillLayerStatus.EMPTY
    assert decision.reason is None


def test_an_admissible_personal_layer_is_applied():
    personal = _resolution(
        _binding("Mina svarspreferenser", position=0),
        _binding("Mötesanteckningar", position=1, mode=ON_DEMAND),
    )

    decision = _assess(
        organisation=_resolution(
            _binding("Klarspråk", position=0, source=SkillBindingSource.ORGANIZATION)
        ),
        personal=personal,
    )

    assert decision.status is PersonalSkillLayerStatus.APPLIED
    assert decision.bindings == personal.eligible


def test_a_missing_permission_suspends_the_layer():
    decision = _assess(
        personal=_resolution(_binding("Mina svarspreferenser", position=0)),
        holds_permission=False,
    )

    assert decision.status is PersonalSkillLayerStatus.SUSPENDED
    assert decision.reason is PersonalSkillLayerReason.PERMISSION_MISSING


def test_blocked_bindings_count_toward_the_combined_limit():
    decision = _assess(
        organisation=_resolution(_binding("Klarspråk", position=0)),
        personal=_resolution(
            _binding("Mina svarspreferenser", position=0),
            blocked=(_binding("Spärrad", position=1),),
        ),
        policy=_policy(max_attached_skills=2),
    )

    assert decision.status is PersonalSkillLayerStatus.SUSPENDED
    assert decision.reason is PersonalSkillLayerReason.ATTACHMENT_LIMIT_EXCEEDED


def test_always_instructions_that_overflow_the_model_window_suspend_the_layer():
    decision = _assess(
        personal=_resolution(_binding("Lång", position=0, instructions="word " * 5000)),
        max_input_tokens=6000,
    )

    assert decision.status is PersonalSkillLayerStatus.SUSPENDED
    assert decision.reason is PersonalSkillLayerReason.MODEL_CONTEXT_EXCEEDED


def test_on_demand_without_tool_calling_is_unavailable():
    decision = _assess(
        personal=_resolution(_binding("Mötesanteckningar", position=0, mode=ON_DEMAND)),
        supports_tool_calling=False,
    )

    assert decision.status is PersonalSkillLayerStatus.SUSPENDED
    assert decision.reason is PersonalSkillLayerReason.ON_DEMAND_UNAVAILABLE
    assert decision.detail == SkillActivationFallbackReason.MODEL_LACKS_TOOL_CALLING


def test_on_demand_with_selective_activation_off_is_unavailable():
    decision = _assess(
        personal=_resolution(_binding("Mötesanteckningar", position=0, mode=ON_DEMAND)),
        policy=_policy(selective_activation_enabled=False),
    )

    assert decision.reason is PersonalSkillLayerReason.ON_DEMAND_UNAVAILABLE
    assert (
        decision.detail == SkillActivationFallbackReason.SELECTIVE_ACTIVATION_DISABLED
    )


def test_a_personal_catalogue_over_the_share_is_unavailable():
    decision = _assess(
        personal=_resolution(
            *(
                _binding(
                    f"Mall {index}",
                    position=index,
                    mode=ON_DEMAND,
                    description="Use for " + "detailed template work " * 40,
                )
                for index in range(20)
            )
        ),
        policy=_policy(context_share_percent=1),
    )

    assert decision.reason is PersonalSkillLayerReason.ON_DEMAND_UNAVAILABLE
    assert decision.detail == SkillActivationFallbackReason.CATALOG_BUDGET_EXCEEDED


def test_a_short_descriptor_over_a_huge_body_does_not_fit():
    decision = _assess(
        personal=_resolution(
            _binding(
                "Stor mall",
                position=0,
                mode=ON_DEMAND,
                description="Use for templates",
                instructions="word " * 20000,
            )
        )
    )

    assert decision.status is PersonalSkillLayerStatus.SUSPENDED
    assert decision.reason is PersonalSkillLayerReason.PERSONAL_SKILL_DOES_NOT_FIT
    assert decision.detail == SkillActivationRejectionReason.CONTEXT_LIMIT_EXCEEDED


def test_personal_always_text_may_not_crowd_out_an_organisation_candidate():
    organisation = _resolution(
        _binding(
            "Organisationens mall",
            position=0,
            mode=ON_DEMAND,
            source=SkillBindingSource.ORGANIZATION,
            instructions="word " * 8000,
        )
    )
    alone = _assess(organisation=organisation)
    assert alone.status is PersonalSkillLayerStatus.EMPTY

    decision = _assess(
        organisation=organisation,
        personal=_resolution(
            _binding("Mina svarspreferenser", position=0, instructions="word " * 6000)
        ),
    )

    assert decision.status is PersonalSkillLayerStatus.SUSPENDED
    assert decision.reason is PersonalSkillLayerReason.ORGANISATION_SKILL_CROWDED_OUT


def test_layers_compose_organisation_first_with_contiguous_positions():
    org_a = _binding("Klarspråk", position=3)
    org_b = _binding("Säkerhet", position=7)
    mine_a = _binding("Mina svarspreferenser", position=0)
    mine_b = _binding("Mötesanteckningar", position=1, mode=ON_DEMAND)

    composed = compose_layers(
        organisation=_resolution(org_a, org_b),
        personal=_resolution(mine_a, mine_b),
    )

    assert [binding.skill_id for binding in composed.eligible] == [
        org_a.skill_id,
        org_b.skill_id,
        mine_a.skill_id,
        mine_b.skill_id,
    ]
    positions = [binding.position for binding in composed.eligible]
    assert positions == sorted(positions)
    assert len(set(positions)) == len(positions)


_APPLIED = PersonalSkillLayerDecision(status=PersonalSkillLayerStatus.APPLIED)
_EMPTY = PersonalSkillLayerDecision(status=PersonalSkillLayerStatus.EMPTY)


def _suspended(reason=PersonalSkillLayerReason.MODEL_CONTEXT_EXCEEDED):
    return PersonalSkillLayerDecision(
        status=PersonalSkillLayerStatus.SUSPENDED, reason=reason
    )


def _save(*, before=None, bindings_changed=False, removal_only=False):
    return PersonalSkillLayerSave(
        before=before, bindings_changed=bindings_changed, removal_only=removal_only
    )


@pytest.mark.parametrize(
    ("save", "after"),
    [
        (_save(bindings_changed=True), _EMPTY),
        (_save(bindings_changed=True), _APPLIED),
        (_save(bindings_changed=True, removal_only=True), _suspended()),
        (_save(before=_suspended()), _suspended()),
        (
            _save(before=_APPLIED),
            _suspended(PersonalSkillLayerReason.PERMISSION_MISSING),
        ),
        (_save(before=None), _suspended()),
    ],
    ids=[
        "switching-off-the-last-skill",
        "an-admissible-change",
        "removing-while-still-over-a-limit",
        "a-model-switch-while-already-paused",
        "a-model-switch-after-revocation",
        "no-stored-decision",
    ],
)
def test_save_transitions_that_are_accepted(save, after):
    assert_personal_skill_layer_save(save, after)


@pytest.mark.parametrize(
    ("save", "after"),
    [
        (_save(bindings_changed=True), _suspended()),
        (_save(before=_APPLIED), _suspended()),
    ],
    ids=["an-addition-that-does-not-fit", "a-model-switch-that-breaks-a-working-layer"],
)
def test_save_transitions_that_are_refused(save, after):
    with pytest.raises(PersonalSkillLayerRejectedError) as raised:
        assert_personal_skill_layer_save(save, after)

    assert raised.value.details == {"reason": "model_context_exceeded", "detail": None}


def test_an_organisation_candidate_that_no_longer_fits_the_window_is_crowded_out():
    # The share is generous here, so only the model window can decide.
    organisation = _resolution(
        _binding(
            "Organisationens mall",
            position=0,
            mode=ON_DEMAND,
            source=SkillBindingSource.ORGANIZATION,
            instructions="word " * 2000,
        )
    )
    policy = _policy(context_share_percent=100)
    alone = _assess(organisation=organisation, policy=policy, max_input_tokens=5000)
    assert alone.status is PersonalSkillLayerStatus.EMPTY

    decision = _assess(
        organisation=organisation,
        personal=_resolution(
            _binding("Mina svarspreferenser", position=0, instructions="word " * 1500)
        ),
        policy=policy,
        max_input_tokens=5000,
    )

    assert decision.reason is PersonalSkillLayerReason.ORGANISATION_SKILL_CROWDED_OUT
    assert (
        decision.detail == SkillActivationRejectionReason.MODEL_CONTEXT_LIMIT_EXCEEDED
    )


def test_a_personal_candidate_that_would_overflow_the_window_does_not_fit():
    decision = _assess(
        personal=_resolution(
            _binding(
                "Stor mall",
                position=0,
                mode=ON_DEMAND,
                description="Use for templates",
                instructions="word " * 3500,
            )
        ),
        policy=_policy(context_share_percent=100),
        max_input_tokens=5000,
    )

    assert decision.reason is PersonalSkillLayerReason.PERSONAL_SKILL_DOES_NOT_FIT
    assert (
        decision.detail == SkillActivationRejectionReason.MODEL_CONTEXT_LIMIT_EXCEEDED
    )
