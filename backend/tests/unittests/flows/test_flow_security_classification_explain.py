"""The classification explain and the raising check are one computation.

Each scenario states the outcome the rule must give, then asserts that the
whole-flow explain reports it and that the raising check refuses with exactly
the violation the explain names (or does not refuse when the explain has none).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_security_classification import (
    explain_flow_security_classification,
    require_flow_security_classification,
)
from eneo.main.exceptions import BadRequestException

MISMATCH = "flow_step_security_classification_mismatch"
WRITE_DOWN = "flow_step_output_classification_write_down"


def _classification(level: int):
    return SimpleNamespace(security_level=level)


def _model(level: int | None, *, can_access: bool = True):
    return SimpleNamespace(
        id=uuid4(),
        security_classification=(_classification(level) if level is not None else None),
        can_access=can_access,
    )


def _collection(level: int):
    return SimpleNamespace(
        embedding_model=SimpleNamespace(security_classification=_classification(level))
    )


def _space(level: int | None, models):
    return SimpleNamespace(
        security_classification=(_classification(level) if level is not None else None),
        completion_models=list(models),
    )


@dataclass(frozen=True)
class _Step:
    model_level: int | None
    input_source: str = "previous_step"
    question: str | None = None
    prompt: str = ""
    knowledge_level: int | None = None
    override: int | None = None
    mode: str = "pass_through"


@dataclass(frozen=True)
class _Expect:
    order: int
    code: str | None = None
    cause: str | None = None
    required_level: int | None = None
    current_level: int | None = None
    sources: tuple[int, ...] = ()
    output: int | None = None
    floor: int | None = None
    reads: tuple[int, ...] = ()
    required_model: int | None = None


@dataclass(frozen=True)
class _Scenario:
    steps: tuple[_Step, ...]
    expect: tuple[_Expect, ...] = ()
    space_level: int | None = 1
    security_enabled: bool = True
    space_models: tuple[int | None, ...] = (1, 2, 3, 4)


HIGH_FIRST = _Step(model_level=3, input_source="flow_input", override=3)


SCENARIOS: dict[str, _Scenario] = {
    "reads-previous-step-low-model": _Scenario(
        steps=(HIGH_FIRST, _Step(model_level=2)),
        expect=(
            _Expect(1, output=3, floor=1, required_model=1),
            _Expect(
                2,
                code=MISMATCH,
                cause="reads",
                required_level=3,
                current_level=2,
                sources=(1,),
                reads=(1,),
                required_model=3,
                output=3,
                floor=3,
            ),
        ),
    ),
    "reads-through-underlag": _Scenario(
        steps=(
            HIGH_FIRST,
            _Step(
                model_level=1,
                input_source="flow_input",
                question="Läs: {{ step_1.output.text }}",
            ),
        ),
        expect=(
            _Expect(1, output=3, floor=1, required_model=1),
            _Expect(
                2,
                code=MISMATCH,
                cause="reads",
                required_level=3,
                current_level=1,
                sources=(1,),
                reads=(1,),
                required_model=3,
                output=3,
                floor=3,
            ),
        ),
    ),
    "reads-through-prompt": _Scenario(
        steps=(
            HIGH_FIRST,
            _Step(
                model_level=1,
                input_source="flow_input",
                question="Fast text.",
                prompt="Bakgrund: {{ step_1.output.text }}",
            ),
        ),
        expect=(
            _Expect(1, output=3, floor=1, required_model=1),
            _Expect(
                2,
                code=MISMATCH,
                cause="reads",
                required_level=3,
                current_level=1,
                sources=(1,),
                reads=(1,),
                required_model=3,
                output=3,
                floor=3,
            ),
        ),
    ),
    "literal-underlag-reads-nothing": _Scenario(
        steps=(HIGH_FIRST, _Step(model_level=1, question="Fast text.")),
        expect=(
            _Expect(1, output=3, floor=1, required_model=1),
            _Expect(2, output=1, floor=1, required_model=1),
        ),
    ),
    "knowledge-sets-the-level": _Scenario(
        steps=(_Step(model_level=2, input_source="flow_input", knowledge_level=3),),
        expect=(
            _Expect(
                1,
                code=MISMATCH,
                cause="knowledge",
                required_level=3,
                current_level=2,
                required_model=3,
                output=3,
                floor=3,
            ),
        ),
    ),
    "knowledge-cleared": _Scenario(
        steps=(_Step(model_level=3, input_source="flow_input", knowledge_level=3),),
        expect=(_Expect(1, required_model=3, output=3, floor=3),),
    ),
    "space-sets-the-level": _Scenario(
        steps=(_Step(model_level=1, input_source="flow_input"),),
        space_level=2,
        expect=(
            _Expect(
                1,
                code=MISMATCH,
                cause="space",
                required_level=2,
                current_level=1,
                required_model=2,
                output=2,
                floor=2,
            ),
        ),
    ),
    "step-without-model-under-a-floor": _Scenario(
        steps=(_Step(model_level=None, input_source="flow_input"),),
        expect=(
            _Expect(
                1,
                code=MISMATCH,
                cause="space",
                required_level=1,
                current_level=None,
                required_model=1,
                output=1,
                floor=1,
            ),
        ),
    ),
    "override-write-down": _Scenario(
        steps=(HIGH_FIRST, _Step(model_level=3, override=1)),
        expect=(
            _Expect(1, output=3, floor=1, required_model=1),
            _Expect(
                2,
                code=WRITE_DOWN,
                cause="reads",
                required_level=3,
                current_level=1,
                sources=(1,),
                reads=(1,),
                required_model=3,
                output=3,
                floor=3,
            ),
        ),
    ),
    "override-raises-the-output": _Scenario(
        steps=(HIGH_FIRST, _Step(model_level=4, override=4)),
        expect=(
            _Expect(1, output=3, floor=1, required_model=1),
            _Expect(2, reads=(1,), required_model=3, output=4, floor=3),
        ),
    ),
    "deterministic-step-carries-the-input-level": _Scenario(
        steps=(
            HIGH_FIRST,
            _Step(model_level=None, mode="render_verbatim"),
        ),
        expect=(
            _Expect(1, output=3, floor=1, required_model=1),
            _Expect(2, reads=(1,), output=3, floor=3),
        ),
    ),
    "deterministic-step-override-write-down": _Scenario(
        steps=(
            HIGH_FIRST,
            _Step(model_level=None, mode="render_verbatim", override=1),
        ),
        expect=(
            _Expect(1, output=3, floor=1, required_model=1),
            _Expect(
                2,
                code=WRITE_DOWN,
                cause="reads",
                required_level=3,
                current_level=1,
                sources=(1,),
                reads=(1,),
                output=3,
                floor=3,
            ),
        ),
    ),
    "mismatch-wins-when-both-rules-are-broken": _Scenario(
        steps=(HIGH_FIRST, _Step(model_level=2, override=1)),
        expect=(
            _Expect(1, output=3, floor=1, required_model=1),
            _Expect(
                2,
                code=MISMATCH,
                cause="reads",
                required_level=3,
                current_level=2,
                sources=(1,),
                reads=(1,),
                required_model=3,
                output=3,
                floor=3,
            ),
        ),
    ),
    "the-raise-names-the-first-violation-the-explain-lists-both": _Scenario(
        steps=(
            _Step(model_level=None, input_source="flow_input"),
            _Step(model_level=0),
        ),
        expect=(
            _Expect(
                1,
                code=MISMATCH,
                cause="space",
                required_level=1,
                current_level=None,
                required_model=1,
                output=1,
                floor=1,
            ),
            _Expect(
                2,
                code=MISMATCH,
                cause="reads",
                required_level=1,
                current_level=0,
                sources=(1,),
                reads=(1,),
                required_model=1,
                output=1,
                floor=1,
            ),
        ),
    ),
    "reads-are-named-before-knowledge-at-the-same-level": _Scenario(
        steps=(
            HIGH_FIRST,
            _Step(model_level=2, knowledge_level=3),
        ),
        expect=(
            _Expect(1, output=3, floor=1, required_model=1),
            _Expect(
                2,
                code=MISMATCH,
                cause="reads",
                required_level=3,
                current_level=2,
                sources=(1,),
                reads=(1,),
                required_model=3,
                output=3,
                floor=3,
            ),
        ),
    ),
    "knowledge-is-named-before-the-space-at-the-same-level": _Scenario(
        steps=(_Step(model_level=1, input_source="flow_input", knowledge_level=2),),
        space_level=2,
        expect=(
            _Expect(
                1,
                code=MISMATCH,
                cause="knowledge",
                required_level=2,
                current_level=1,
                required_model=2,
                output=2,
                floor=2,
            ),
        ),
    ),
    "nothing-classified": _Scenario(
        space_level=None,
        steps=(
            _Step(model_level=None, input_source="flow_input"),
            _Step(model_level=None),
        ),
        expect=(_Expect(1), _Expect(2, reads=(1,))),
    ),
    "classification-disabled": _Scenario(
        # The stored levels and overrides stay on the rows; none of them applies.
        space_level=3,
        security_enabled=False,
        steps=(
            _Step(
                model_level=1,
                input_source="flow_input",
                knowledge_level=4,
                override=4,
            ),
            _Step(model_level=1, override=1),
            _Step(model_level=1),
        ),
        expect=(_Expect(1), _Expect(2, reads=(1,)), _Expect(3, reads=(2,))),
    ),
}


def _assistant(spec: _Step):
    return SimpleNamespace(
        completion_model=(
            _model(spec.model_level) if spec.model_level is not None else None
        ),
        collections=(
            [_collection(spec.knowledge_level)]
            if spec.knowledge_level is not None
            else []
        ),
        websites=[],
        integration_knowledge_list=[],
        get_prompt_text=lambda: spec.prompt,
    )


@dataclass
class _Flow:
    security_enabled: bool = True
    steps: list[FlowStep] = field(default_factory=list)
    assistants: dict[UUID, SimpleNamespace] = field(default_factory=dict)
    space: SimpleNamespace | None = None


def _build(scenario: _Scenario) -> _Flow:
    flow = _Flow(security_enabled=scenario.security_enabled)
    for order, spec in enumerate(scenario.steps, start=1):
        assistant = _assistant(spec)
        step = FlowStep(
            id=uuid4(),
            assistant_id=uuid4(),
            step_order=order,
            user_description=f"Step {order}",
            input_source=spec.input_source,
            input_type="text",
            output_mode=spec.mode,
            output_type="text",
            input_bindings=(
                {"question": spec.question} if spec.question is not None else None
            ),
            output_classification_override=spec.override,
        )
        flow.steps.append(step)
        flow.assistants[step.assistant_id] = assistant
    flow.space = _space(
        scenario.space_level,
        [_model(level) for level in scenario.space_models],
    )
    return flow


@pytest.mark.parametrize("name", SCENARIOS)
def test_the_explain_reports_the_rule_outcome(name: str) -> None:
    scenario = SCENARIOS[name]
    flow = _build(scenario)

    explained = explain_flow_security_classification(
        steps=flow.steps,
        assistants_by_id=flow.assistants,
        space=flow.space,
        security_enabled=flow.security_enabled,
    )

    assert [item.step_order for item in explained] == [
        expect.order for expect in scenario.expect
    ]
    for item, expect in zip(explained, scenario.expect, strict=True):
        actual_violation = (
            None
            if item.violation is None
            else (
                item.violation.code.value,
                item.violation.cause.value,
                item.violation.required_level,
                item.violation.current_level,
                item.violation.source_step_orders,
            )
        )
        expected_violation = (
            None
            if expect.code is None
            else (
                expect.code,
                expect.cause,
                expect.required_level,
                expect.current_level,
                expect.sources,
            )
        )
        assert actual_violation == expected_violation, f"step {expect.order}"
        assert item.reads == expect.reads, f"step {expect.order}"
        assert item.required_model_level == expect.required_model, (
            f"step {expect.order}"
        )
        assert item.effective_output_level == expect.output, f"step {expect.order}"
        assert item.output_floor == expect.floor, f"step {expect.order}"


@pytest.mark.parametrize("name", SCENARIOS)
def test_the_raising_check_refuses_exactly_what_the_explain_names(name: str) -> None:
    scenario = SCENARIOS[name]
    flow = _build(scenario)
    explained = explain_flow_security_classification(
        steps=flow.steps,
        assistants_by_id=flow.assistants,
        space=flow.space,
        security_enabled=flow.security_enabled,
    )
    first = next((item for item in explained if item.violation is not None), None)

    if first is None:
        require_flow_security_classification(
            steps=flow.steps,
            assistants_by_id=flow.assistants,
            space=flow.space,
            security_enabled=flow.security_enabled,
        )
        return

    with pytest.raises(BadRequestException) as exc_info:
        require_flow_security_classification(
            steps=flow.steps,
            assistants_by_id=flow.assistants,
            space=flow.space,
            security_enabled=flow.security_enabled,
        )

    violation = first.violation
    assert violation is not None
    error = exc_info.value
    assert error.code == violation.code.value
    assert str(error) == violation.message
    assert error.context is not None
    assert error.context["step_order"] == first.step_order
    assert error.context["required_level"] == violation.required_level
    assert error.context["current_level"] == violation.current_level
    assert error.context["cause"] == violation.cause.value
    if violation.code.value == MISMATCH:
        assert first.qualifying_model_ids is not None
        assert error.context["qualifying_model_ids"] == [
            str(model_id) for model_id in first.qualifying_model_ids
        ]
    else:
        assert "qualifying_model_ids" not in error.context


def test_qualifying_models_are_the_usable_space_models_that_clear_the_requirement() -> (
    None
):
    cleared = _model(3)
    higher = _model(4)
    too_low = _model(2)
    unclassified = _model(None)
    unusable = _model(4, can_access=False)
    scenario = _Scenario(
        steps=(HIGH_FIRST, _Step(model_level=2)),
        space_models=(),
    )
    flow = _build(scenario)
    flow.space = _space(1, [too_low, unclassified, unusable, higher, cleared])

    explained = explain_flow_security_classification(
        steps=flow.steps,
        assistants_by_id=flow.assistants,
        space=flow.space,
        security_enabled=flow.security_enabled,
    )

    assert set(explained[1].qualifying_model_ids) == {cleared.id, higher.id}
    # Lowest sufficient level first, so "the closest fit" leads the picker.
    assert explained[1].qualifying_model_ids == (cleared.id, higher.id)
    assert explained[1].model_level == 2


def test_with_nothing_classified_every_usable_model_qualifies() -> None:
    usable = _model(None)
    unusable = _model(None, can_access=False)
    flow = _build(
        _Scenario(
            steps=(_Step(model_level=None, input_source="flow_input"),),
            space_level=None,
            space_models=(),
        )
    )
    flow.space = _space(None, [usable, unusable])

    (only,) = explain_flow_security_classification(
        steps=flow.steps,
        assistants_by_id=flow.assistants,
        space=flow.space,
        security_enabled=flow.security_enabled,
    )

    assert only.required_model_level is None
    assert only.qualifying_model_ids == (usable.id,)


def test_a_disabled_classification_disappears_from_the_explain_entirely() -> None:
    flow = _build(SCENARIOS["classification-disabled"])
    assert flow.space is not None
    flow.space.completion_models = [_model(1), _model(4)]

    explained = explain_flow_security_classification(
        steps=flow.steps,
        assistants_by_id=flow.assistants,
        space=flow.space,
        security_enabled=False,
    )

    for item in explained:
        assert item.input_level is None
        assert item.knowledge_level is None
        assert item.model_level is None
        assert item.required_model_level is None
        assert item.effective_output_level is None
        assert item.output_floor is None
        assert item.violation is None


def test_the_same_flow_is_classified_and_refused_while_the_tenant_has_it_enabled() -> (
    None
):
    scenario = SCENARIOS["classification-disabled"]
    flow = _build(scenario)

    explained = explain_flow_security_classification(
        steps=flow.steps,
        assistants_by_id=flow.assistants,
        space=flow.space,
        security_enabled=True,
    )

    assert explained[0].effective_output_level == 4
    assert explained[1].violation is not None


class _ScannedModel:
    """A space model that counts how often the rule reads it."""

    def __init__(self, level: int) -> None:
        self.id = uuid4()
        self._level = level
        self.reads = 0

    @property
    def can_access(self) -> bool:
        self.reads += 1
        return True

    @property
    def security_classification(self):
        return _classification(self._level)


class _RecordingAssistants(dict):
    """The assistants of a flow, remembering which steps the rule asked for."""

    def __init__(self, items) -> None:
        super().__init__(items)
        self.asked: list[UUID] = []

    def __getitem__(self, key):
        self.asked.append(key)
        return super().__getitem__(key)


def test_a_write_that_clears_every_step_reads_no_model_of_the_space() -> None:
    flow = _build(SCENARIOS["knowledge-cleared"])
    models = [_ScannedModel(level) for level in (1, 2, 3, 4)]
    flow.space = _space(1, [])
    flow.space.completion_models = models

    require_flow_security_classification(
        steps=flow.steps,
        assistants_by_id=flow.assistants,
        space=flow.space,
        security_enabled=True,
    )

    assert sum(model.reads for model in models) == 0


def test_a_refused_write_stops_at_the_first_refusal_and_reads_the_models_once() -> None:
    flow = _build(
        SCENARIOS["the-raise-names-the-first-violation-the-explain-lists-both"]
    )
    models = [_ScannedModel(level) for level in (1, 2, 3, 4)]
    flow.space = _space(1, [])
    flow.space.completion_models = models
    assistants = _RecordingAssistants(flow.assistants)

    with pytest.raises(BadRequestException) as exc_info:
        require_flow_security_classification(
            steps=flow.steps,
            assistants_by_id=assistants,
            space=flow.space,
            security_enabled=True,
        )

    assert exc_info.value.context is not None
    assert exc_info.value.context["step_order"] == 1
    assert exc_info.value.context["qualifying_model_ids"] == [
        str(model.id) for model in models
    ]
    assert assistants.asked == [flow.steps[0].assistant_id]
    assert [model.reads for model in models] == [1, 1, 1, 1]


def test_the_preview_reads_the_space_models_once_per_distinct_level() -> None:
    flow = _build(
        _Scenario(steps=(HIGH_FIRST, _Step(model_level=3), _Step(model_level=3)))
    )
    models = [_ScannedModel(level) for level in (1, 2, 3, 4)]
    flow.space = _space(1, [])
    flow.space.completion_models = models

    explained = explain_flow_security_classification(
        steps=flow.steps,
        assistants_by_id=flow.assistants,
        space=flow.space,
        security_enabled=True,
    )

    assert [item.required_model_level for item in explained] == [1, 3, 3]
    assert [len(item.qualifying_model_ids or ()) for item in explained] == [4, 2, 2]
    # Levels 1 and 3 are the distinct requirements: two passes, not three.
    assert [model.reads for model in models] == [2, 2, 2, 2]
