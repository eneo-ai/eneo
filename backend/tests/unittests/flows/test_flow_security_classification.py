from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_error_taxonomy import FLOW_ERROR_TAXONOMY
from eneo.flows.flow_security_classification import (
    ClassificationViolationCode,
    evaluate_step_security_classification,
    evidence_classification_level,
)
from eneo.main.exceptions import BadRequestException


def _classification(level: int):
    return SimpleNamespace(security_level=level)


def _assistant(
    *,
    model_level: int | None,
    knowledge_level: int | None = None,
):
    completion_model = (
        SimpleNamespace(security_classification=_classification(model_level))
        if model_level is not None
        else None
    )
    collections = (
        [
            SimpleNamespace(
                embedding_model=SimpleNamespace(
                    security_classification=_classification(knowledge_level)
                )
            )
        ]
        if knowledge_level is not None
        else []
    )
    return SimpleNamespace(
        completion_model=completion_model,
        collections=collections,
        websites=[],
        integration_knowledge_list=[],
    )


def _space(level: int | None):
    return SimpleNamespace(
        security_classification=(_classification(level) if level is not None else None)
    )


def _space_model(level: int | None, *, can_access: bool = True):
    return SimpleNamespace(
        id=uuid4(),
        security_classification=_classification(level) if level is not None else None,
        can_access=can_access,
    )


def test_rejects_model_below_previous_step_classification() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        evaluate_step_security_classification(
            step_order=2,
            upstream_step_orders=[1],
            output_mode="pass_through",
            output_classification_override=None,
            prior_output_levels_by_order={1: 3},
            assistant=_assistant(model_level=2),
            space=_space(1),
            security_enabled=True,
        )

    assert exc_info.value.code == "flow_step_security_classification_mismatch"


def test_rejects_output_override_write_down() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        evaluate_step_security_classification(
            step_order=2,
            upstream_step_orders=[1],
            output_mode="pass_through",
            output_classification_override=1,
            prior_output_levels_by_order={1: 3},
            assistant=_assistant(model_level=3),
            space=_space(1),
            security_enabled=True,
        )

    assert exc_info.value.code == "flow_step_output_classification_write_down"


def test_returns_effective_output_level_when_security_is_compatible() -> None:
    evaluation = evaluate_step_security_classification(
        step_order=2,
        upstream_step_orders=[1],
        output_mode="pass_through",
        output_classification_override=4,
        prior_output_levels_by_order={1: 3},
        assistant=_assistant(model_level=4, knowledge_level=3),
        space=_space(1),
        security_enabled=True,
    )

    assert evaluation.required_model_level == 3
    assert evaluation.effective_output_level == 4


def test_current_step_output_override_does_not_raise_same_step_input_floor() -> None:
    evaluation = evaluate_step_security_classification(
        step_order=1,
        upstream_step_orders=[],
        output_mode="pass_through",
        output_classification_override=3,
        prior_output_levels_by_order={},
        assistant=_assistant(model_level=3),
        space=_space(None),
        security_enabled=True,
    )

    assert evaluation.required_model_level is None
    assert evaluation.effective_output_level == 3


def test_all_previous_steps_uses_max_prior_effective_output_level() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        evaluate_step_security_classification(
            step_order=4,
            upstream_step_orders=[1, 2, 3],
            output_mode="pass_through",
            output_classification_override=None,
            prior_output_levels_by_order={1: 1, 2: 3, 3: 2},
            assistant=_assistant(model_level=2),
            space=_space(1),
            security_enabled=True,
        )

    assert exc_info.value.code == "flow_step_security_classification_mismatch"


def test_deterministic_step_without_model_carries_input_classification() -> None:
    # A rendering step runs no completion model, so there is no model to hold
    # to the floor. Its output still inherits the classification of its input.
    evaluation = evaluate_step_security_classification(
        step_order=3,
        upstream_step_orders=[1, 2],
        output_mode="render_verbatim",
        output_classification_override=None,
        prior_output_levels_by_order={1: 1, 2: 3},
        assistant=_assistant(model_level=None),
        space=_space(1),
        security_enabled=True,
    )

    assert evaluation.required_model_level is None
    assert evaluation.effective_output_level == 3


def test_deterministic_step_still_rejects_output_override_write_down() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        evaluate_step_security_classification(
            step_order=2,
            upstream_step_orders=[1],
            output_mode="render_verbatim",
            output_classification_override=1,
            prior_output_levels_by_order={1: 3},
            assistant=_assistant(model_level=None),
            space=_space(None),
            security_enabled=True,
        )

    assert exc_info.value.code == "flow_step_output_classification_write_down"


def test_underlag_floor_reads_only_the_steps_it_binds() -> None:
    # Declared all_previous_steps, but the underlag reads step 2 only: the
    # higher classification of the unread step 1 is not the floor.
    evaluation = evaluate_step_security_classification(
        step_order=3,
        upstream_step_orders=[2],
        output_mode="pass_through",
        output_classification_override=None,
        prior_output_levels_by_order={1: 3, 2: 1},
        assistant=_assistant(model_level=2),
        space=_space(1),
        security_enabled=True,
    )

    assert evaluation.required_model_level == 1
    assert evaluation.effective_output_level == 1


def test_completion_step_without_model_is_rejected_when_floor_exists() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        evaluate_step_security_classification(
            step_order=1,
            upstream_step_orders=[],
            output_mode="pass_through",
            output_classification_override=None,
            prior_output_levels_by_order={},
            assistant=_assistant(model_level=None),
            space=_space(1),
            security_enabled=True,
        )

    assert exc_info.value.code == "flow_step_security_classification_mismatch"


def test_evidence_classification_level_is_the_runs_highest_step_level():
    assert evidence_classification_level({1: None, 2: 3, 3: 1}) == 3
    # An unclassified run records 0 so it can be told from a run that predates the rule.
    assert evidence_classification_level({1: None}) == 0
    assert evidence_classification_level({}) == 0


def _raise_mismatch(**overrides):
    step_id = uuid4()
    models = overrides.pop("models", [])
    kwargs = dict(
        step_order=3,
        step_id=step_id,
        upstream_step_orders=[1],
        output_mode="pass_through",
        output_classification_override=None,
        prior_output_levels_by_order={1: 3, 2: 1},
        assistant=_assistant(model_level=2),
        space=_space(1),
        completion_models=models,
    )
    kwargs.update(overrides)
    with pytest.raises(BadRequestException) as exc_info:
        evaluate_step_security_classification(
            **kwargs,
            security_enabled=True,
        )
    return exc_info.value, step_id


def test_mismatch_carries_the_facts_the_editor_needs_to_act() -> None:
    cleared = _space_model(3)
    too_low = _space_model(2)
    unusable = _space_model(4, can_access=False)
    error, step_id = _raise_mismatch(models=[too_low, cleared, unusable])

    assert error.code == "flow_step_security_classification_mismatch"
    assert error.context == {
        "issue_code": "flow_step_security_classification_mismatch",
        "step_order": 3,
        "step_id": str(step_id),
        "required_level": 3,
        "current_level": 2,
        "cause": "reads",
        "source_step_orders": [1],
        "qualifying_model_ids": [str(cleared.id)],
    }


def test_mismatch_names_knowledge_as_the_cause_when_no_read_reaches_the_level() -> None:
    error, _ = _raise_mismatch(
        upstream_step_orders=[2],
        assistant=_assistant(model_level=2, knowledge_level=3),
    )

    assert error.context["cause"] == "knowledge"
    assert error.context["source_step_orders"] == []
    assert error.context["required_level"] == 3


def test_mismatch_names_the_space_when_it_alone_sets_the_level() -> None:
    error, _ = _raise_mismatch(
        upstream_step_orders=[],
        assistant=_assistant(model_level=None),
        space=_space(2),
    )

    assert error.context["cause"] == "space"
    assert error.context["required_level"] == 2
    assert error.context["current_level"] is None


def test_write_down_carries_the_floor_and_the_override() -> None:
    step_id = uuid4()
    with pytest.raises(BadRequestException) as exc_info:
        evaluate_step_security_classification(
            step_order=2,
            step_id=step_id,
            upstream_step_orders=[1],
            output_mode="pass_through",
            output_classification_override=1,
            prior_output_levels_by_order={1: 3},
            assistant=_assistant(model_level=3),
            space=_space(1),
            security_enabled=True,
        )

    assert exc_info.value.code == "flow_step_output_classification_write_down"
    assert exc_info.value.context == {
        "issue_code": "flow_step_output_classification_write_down",
        "step_order": 2,
        "step_id": str(step_id),
        "required_level": 3,
        "current_level": 1,
        "cause": "reads",
        "source_step_orders": [1],
    }


def test_messages_stay_the_ones_clients_already_read() -> None:
    with pytest.raises(BadRequestException) as mismatch:
        evaluate_step_security_classification(
            step_order=3,
            upstream_step_orders=[1],
            output_mode="pass_through",
            output_classification_override=None,
            prior_output_levels_by_order={1: 3},
            assistant=_assistant(model_level=2),
            space=_space(1),
            security_enabled=True,
        )
    assert str(mismatch.value) == (
        "Step 3: assistant model does not meet the required security classification."
    )
    with pytest.raises(BadRequestException) as exc_info:
        evaluate_step_security_classification(
            step_order=2,
            upstream_step_orders=[1],
            output_mode="pass_through",
            output_classification_override=1,
            prior_output_levels_by_order={1: 3},
            assistant=_assistant(model_level=3),
            space=_space(1),
            security_enabled=True,
        )
    assert str(exc_info.value) == (
        "Step 2: output classification override would lower the effective "
        "classification of the step output."
    )


def test_a_disabled_classification_sets_no_level_and_refuses_nothing() -> None:
    # The organization turned classifications off: the space, the model, the
    # knowledge and a stored override still carry a level, but none of it applies.
    assistant = SimpleNamespace(
        completion_model=SimpleNamespace(security_classification=_classification(1)),
        collections=[
            SimpleNamespace(
                embedding_model=SimpleNamespace(
                    security_classification=_classification(4)
                )
            )
        ],
        websites=[],
        integration_knowledge_list=[],
    )

    evaluation = evaluate_step_security_classification(
        step_order=2,
        upstream_step_orders=[1],
        output_mode="pass_through",
        output_classification_override=2,
        prior_output_levels_by_order={1: None},
        assistant=assistant,
        space=_space(3),
        security_enabled=False,
    )

    assert evaluation.required_model_level is None
    assert evaluation.model_level is None
    assert evaluation.effective_output_level is None
    assert evaluation.output_floor is None


def test_a_stored_override_sets_no_output_level_while_classifications_are_off() -> None:
    kwargs = dict(
        step_order=1,
        upstream_step_orders=[],
        output_mode="pass_through",
        output_classification_override=3,
        prior_output_levels_by_order={},
        assistant=_assistant(model_level=1),
        space=_space(None),
    )

    off = evaluate_step_security_classification(**kwargs, security_enabled=False)
    on = evaluate_step_security_classification(**kwargs, security_enabled=True)

    assert off.effective_output_level is None
    assert on.effective_output_level == 3


def test_the_two_refusal_codes_are_public_catalog_codes() -> None:
    # A client branches on these codes, so they belong to the closed catalog
    # with a recovery entry, not to strings the classification module owns.
    codes = {
        "flow_step_security_classification_mismatch",
        "flow_step_output_classification_write_down",
    }
    assert {code.value for code in ClassificationViolationCode} == codes
    for code in codes:
        catalogued = FlowApiErrorCode(code)
        entry = FLOW_ERROR_TAXONOMY[catalogued]
        assert entry.surfaced_through == "API error response"


def test_the_raised_refusals_carry_catalog_codes() -> None:
    with pytest.raises(BadRequestException) as mismatch:
        evaluate_step_security_classification(
            step_order=2,
            upstream_step_orders=[1],
            output_mode="pass_through",
            output_classification_override=None,
            prior_output_levels_by_order={1: 3},
            assistant=_assistant(model_level=2),
            space=_space(1),
            security_enabled=True,
        )
    with pytest.raises(BadRequestException) as write_down:
        evaluate_step_security_classification(
            step_order=2,
            upstream_step_orders=[1],
            output_mode="pass_through",
            output_classification_override=1,
            prior_output_levels_by_order={1: 3},
            assistant=_assistant(model_level=3),
            space=_space(1),
            security_enabled=True,
        )

    assert (
        FlowApiErrorCode(mismatch.value.code)
        is FlowApiErrorCode.STEP_SECURITY_CLASSIFICATION_MISMATCH
    )
    assert (
        FlowApiErrorCode(write_down.value.code)
        is FlowApiErrorCode.STEP_OUTPUT_CLASSIFICATION_WRITE_DOWN
    )
