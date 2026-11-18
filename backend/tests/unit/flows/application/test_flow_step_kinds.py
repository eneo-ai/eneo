"""Every answer about which kinds of step a draft allows is what the editor's
save does with the change the answer describes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from eneo.flows.api.flow_definition_access import FlowPermissions
from eneo.flows.application import flow_authoring_operations
from eneo.flows.application.flow_service import FlowService
from eneo.flows.application.flow_step_kinds import (
    StepKindChange,
    StepKindOption,
    editor_update,
    insertion_change,
    step_kind_answer,
)
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.domain.flow_run_retention_policy import (
    FlowRunRetentionContributors,
    FlowRunRetentionOff,
)
from eneo.flows.domain.step_kinds import (
    STEP_KIND_DESCRIPTIONS,
    STEP_KIND_REQUIRED_VALUES,
    STEP_KIND_VALUES,
    FlowStepKind,
    StepKindValues,
    check_step_kind_values,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_authoring_spec import MAX_FLOW_AUTHORING_STEPS
from eneo.main.exceptions import BadRequestException

_URL = "https://example.org/hook"
_TOOL = {"mcp_server_id": str(uuid4()), "tool_id": str(uuid4()), "arguments": {}}
_TRANSCRIBING = {"wizard": {"transcription_enabled": True}}
_AUDIO_UPLOADS = {
    "runtime_input": {"enabled": True, "required": True, "input_format": "audio"}
}
_DOCUMENT_UPLOADS = {
    "runtime_input": {"enabled": True, "required": True, "input_format": "document"}
}
_HTTP_OUT = {
    "url": _URL,
    "auth": {"mode": "none"},
    "timeout_seconds": 30,
    "body": {"mode": "auto"},
    "custom_headers": [],
}


def _step(order: int, **columns: Any) -> FlowStep:
    values: dict[str, Any] = {
        "id": uuid4(),
        "assistant_id": uuid4(),
        "step_order": order,
        "user_description": f"Step {order}",
        "input_source": "flow_input" if order == 1 else "previous_step",
        "input_type": "text",
        "output_mode": "pass_through",
        "output_type": "text",
    }
    return FlowStep.model_validate({**values, **columns})


def _flow(steps: list[FlowStep], **fields: Any) -> Flow:
    now = datetime.now(timezone.utc)
    return Flow.model_validate(
        {
            "id": uuid4(),
            "tenant_id": uuid4(),
            "space_id": uuid4(),
            "space_name": "Space",
            "name": "Flow",
            "created_by_user_id": uuid4(),
            "owner_user_id": uuid4(),
            "run_history_retention": FlowRunRetentionOff(
                contributors=FlowRunRetentionContributors(
                    organization=None, space=None, flow=None
                )
            ),
            "draft_revision": 3,
            "created_at": now,
            "updated_at": now,
            "steps": steps,
            **fields,
        }
    )


def _reading_draft() -> tuple[Flow, dict[UUID, str]]:
    """Step 3's prompt reads step 2 by its alias, so a step put before step 2
    moves the read along."""
    steps = [_step(1), _step(2), _step(3)]
    return _flow(steps), {steps[2].assistant_id: "Check {{step_2}} against {{step_1}}."}


DRAFTS: dict[str, Callable[[], tuple[Flow, dict[UUID, str]]]] = {
    "empty": lambda: (_flow([]), {}),
    "one text step": lambda: (_flow([_step(1)]), {}),
    "structured chain": lambda: (
        _flow(
            [
                _step(1, output_type="json"),
                _step(2, input_type="json", output_type="json"),
            ]
        ),
        {},
    ),
    "transcript and speakers": lambda: (
        _flow(
            [
                _step(
                    1,
                    input_type="audio",
                    input_config=_AUDIO_UPLOADS,
                    output_mode="transcribe_only",
                ),
                _step(
                    2,
                    output_mode="speaker_mapping",
                    output_type="json",
                    review_policy={"mode": "edit"},
                ),
            ],
            metadata_json=_TRANSCRIBING,
        ),
        {},
    ),
    "uploads first": lambda: (
        _flow(
            [
                _step(1, input_type="document", input_config=_DOCUMENT_UPLOADS),
                _step(2),
            ]
        ),
        {},
    ),
    "text and uploads first": lambda: (
        _flow([_step(1, input_config=_DOCUMENT_UPLOADS), _step(2)]),
        {},
    ),
    "sends last": lambda: (
        _flow([_step(1), _step(2, output_mode="http_post", output_config=_HTTP_OUT)]),
        {},
    ),
    "tool first": lambda: (
        _flow(
            [
                _step(
                    1,
                    input_source="tool",
                    input_config={"tool": _TOOL},
                    output_mode="compose_text",
                ),
                _step(2),
            ]
        ),
        {},
    ),
    "reads by alias": _reading_draft,
    "document before a JSON reader": lambda: (
        _flow([_step(1, output_mode="render_verbatim", output_type="docx"), _step(2)]),
        {},
    ),
    # Saved under rules that no longer hold: every change is refused until
    # the step that breaks them is changed.
    "already broken": lambda: (
        _flow([_step(1), _step(2, input_type="json")]),
        {},
    ),
    "published": lambda: (_flow([_step(1)], published_version=1), {}),
}


def _completed(configuration: dict[str, object]) -> dict[str, object]:
    """The configuration as an author completes it: a URL, a tool."""
    done = dict(configuration)
    if done["input_source"] == "http_get":
        done["input_config"] = {**_dict(done["input_config"]), "url": _URL}
    if done["input_source"] == "tool":
        done["input_config"] = {"tool": _TOOL}
    if done["output_mode"] == "http_post":
        done["output_config"] = {**_dict(done["output_config"]), "url": _URL}
    return done


def _dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return dict(value)


async def _save(
    flow: Flow,
    change: StepKindChange,
    prompts: dict[UUID, str],
    monkeypatch: pytest.MonkeyPatch,
    *,
    position: int | None = None,
    step_id: UUID | None = None,
    saved: list[Flow] | None = None,
) -> BadRequestException | ValidationError | None:
    """The editor's save of ``change``: its refusal, or None when it saves;
    the saved flow is appended to ``saved``."""
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=flow.tenant_id,
        permissions=[],
        tenant=SimpleNamespace(security_enabled=False, flow_settings={}),
    )
    flow_repo = AsyncMock()
    flow_repo.get.return_value = flow
    flow_repo.update.side_effect = lambda **kwargs: kwargs["flow"]
    flow_repo.orphaned_flow_managed_assistant_ids.return_value = set()
    service = FlowService(
        user=user,  # type: ignore[arg-type]
        flow_repo=flow_repo,
        flow_version_repo=AsyncMock(),
        assistant_service=AsyncMock(),
    )
    service._validate_assistant_scope_for_steps = AsyncMock()  # type: ignore[method-assign]
    service.reserve_draft_revision = AsyncMock()  # type: ignore[method-assign]
    service.create_flow_assistant = AsyncMock(  # type: ignore[method-assign]
        return_value=(SimpleNamespace(id=uuid4(), name="Added step"), [])
    )
    service.update_reserved_flow_assistant = AsyncMock(  # type: ignore[method-assign]
        side_effect=lambda **kwargs: (
            SimpleNamespace(id=kwargs["assistant_id"], name="Assistant"),
            [],
        )
    )
    service.get_flow_assistant_prompts = AsyncMock(  # type: ignore[method-assign]
        return_value={
            assistant_id: SimpleNamespace(text=text, description=None)
            for assistant_id, text in prompts.items()
        }
    )
    container = MagicMock()
    container.flow_service.return_value = service
    container.user.return_value = user
    container.audit_service.return_value = AsyncMock()
    monkeypatch.setattr(
        flow_authoring_operations,
        "require_flow_edit_access",
        AsyncMock(
            return_value=SimpleNamespace(
                flow=flow, actor=MagicMock(), scope_filter=None
            )
        ),
    )
    monkeypatch.setattr(
        flow_authoring_operations,
        "flow_permissions",
        lambda *_, **__: FlowPermissions(
            can_edit=True,
            can_publish=True,
            can_delete=True,
            can_run=True,
            can_view_runs=True,
        ),
    )
    try:
        update = editor_update(
            flow,
            change,
            expected_revision=flow.draft_revision,
            position=position,
            step_id=step_id,
            name="Added step",
        )
        await flow_authoring_operations.apply_editor_update(
            flow.require_persisted_id(),
            SimpleNamespace(state=SimpleNamespace()),  # type: ignore[arg-type]
            update,
            container,
        )
    except (BadRequestException, ValidationError) as exc:
        return exc
    if saved is not None:
        saved.append(flow_repo.update.call_args.kwargs["flow"])
    return None


def _assert_save_agrees(
    option: StepKindOption, refusal: BadRequestException | ValidationError | None
) -> None:
    where = f"{option.kind.value}: {[r.message for r in option.refusals]}"
    assert option.allowed is (refusal is None), f"{where}; the save gave {refusal!r}"
    if isinstance(refusal, BadRequestException):
        first = option.refusals[0]
        context = refusal.context or {}
        assert (first.code, first.issue_code, first.step_order) == (
            refusal.code,
            context.get("issue_code"),
            context.get("step_order"),
        ), where


def _every_place(flow: Flow) -> dict[str, Any]:
    return {
        "positions": range(1, len(flow.steps) + 2),
        "step_ids": [step.id for step in flow.steps],
    }


@pytest.mark.parametrize("draft", DRAFTS)
async def test_every_answer_is_what_the_editor_save_does(
    draft: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    flow, prompts = DRAFTS[draft]()
    answer = step_kind_answer(flow, prompts=prompts, **_every_place(flow))

    assert [place.position for place in answer.insertions] == list(
        range(1, len(flow.steps) + 2)
    )
    assert [place.step_id for place in answer.steps] == [s.id for s in flow.steps]
    for place in (*answer.insertions, *answer.steps):
        assert [option.kind for option in place.options] == list(FlowStepKind)
        for option in place.options:
            change = StepKindChange(
                configuration=_completed(option.change.configuration),
                step_edits=option.change.step_edits,
                turns_on_transcription=option.change.turns_on_transcription,
            )
            refusal = await _save(
                flow,
                change,
                prompts,
                monkeypatch,
                position=place.position if place.step_id is None else None,
                step_id=place.step_id,
            )
            _assert_save_agrees(option, refusal)


async def test_a_full_flow_takes_no_new_step_but_its_steps_may_change_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = _flow([_step(order) for order in range(1, MAX_FLOW_AUTHORING_STEPS + 1)])
    last = flow.steps[-1]
    assert last.id is not None
    answer = step_kind_answer(
        flow,
        prompts={},
        positions=[MAX_FLOW_AUTHORING_STEPS + 1],
        step_ids=[last.id],
    )

    (insertion,) = answer.insertions
    for option in insertion.options:
        assert [refusal.code for refusal in option.refusals] == [
            "flow_step_limit_exceeded"
        ]
        refusal = await _save(
            flow,
            option.change,
            {},
            monkeypatch,
            position=insertion.position,
        )
        # The editor update refuses the longer step order before the rules.
        assert isinstance(refusal, ValidationError)
    (step,) = answer.steps
    compose = next(o for o in step.options if o.kind is FlowStepKind.COMPOSE)
    assert compose.allowed
    assert await _save(flow, compose.change, {}, monkeypatch, step_id=last.id) is None


def test_a_published_flow_refuses_every_change_as_the_save_does() -> None:
    flow, prompts = DRAFTS["published"]()
    answer = step_kind_answer(flow, prompts=prompts, **_every_place(flow))

    codes = {
        refusal.code
        for place in (*answer.insertions, *answer.steps)
        for option in place.options
        for refusal in option.refusals
    }
    assert codes == {FlowApiErrorCode.UNPUBLISH_REQUIRED.value}


def test_a_step_added_first_takes_the_run_input_over() -> None:
    first = _step(1, input_type="json", output_type="json")
    flow = _flow([first])
    answer = step_kind_answer(flow, prompts={}, positions=[1], step_ids=[])

    by_kind = {option.kind: option for option in answer.insertions[0].options}
    document = by_kind[FlowStepKind.DOCUMENT]
    assert document.change.configuration["input_source"] == "flow_input"
    # A Word document feeds text, not the JSON the old first step read.
    assert document.change.step_edits == (
        (first.id, {"input_source": "previous_step", "input_type": "text"}),
    )
    assert by_kind[FlowStepKind.TRANSCRIBE].change.turns_on_transcription
    assert by_kind[FlowStepKind.REVIEW].refusals[0].issue_code == (
        "typed_io_invalid_input_source_position"
    )


def test_the_update_carries_the_revision_its_caller_read() -> None:
    # The caller read revision 1; the draft has moved on to 3 since. The
    # update is saved against what the caller read, so the save refuses it
    # as stale instead of applying it over a change the caller never saw.
    flow = _flow([_step(1)])
    change = step_kind_answer(flow, prompts={}, positions=[2], step_ids=[])
    option = change.insertions[0].options[0]

    update = editor_update(flow, option.change, expected_revision=1, position=2)

    assert flow.draft_revision == 3
    assert update.expected_revision == 1


async def _added(
    flow: Flow,
    kind: FlowStepKind,
    values: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    *,
    position: int | None = None,
) -> FlowStep:
    """The step a kind with ``values`` is saved as, by the editor's save."""
    place = position or len(flow.steps) + 1
    kind_values = StepKindValues.model_validate(values)
    check_step_kind_values(kind, kind_values)
    change = insertion_change(flow, kind, position=place, values=kind_values)
    saved: list[Flow] = []
    refusal = await _save(flow, change, {}, monkeypatch, position=place, saved=saved)
    assert refusal is None, refusal
    return next(step for step in saved[0].steps if step.step_order == place)


_FACTS = '{"beslut": "Bifall", "datum": "2026-11-11"}'
_READ = {"question": "Läs {{ step_1.output.text }}"}
_TOOL = {"mcp_server_id": str(uuid4()), "tool_id": str(uuid4()), "arguments": {}}


@pytest.mark.parametrize(
    ("kind", "values", "saved"),
    [
        (
            FlowStepKind.AI,
            {"instruction": "Sammanfatta.", "review": {"mode": "view"}},
            {
                "output_mode": "pass_through",
                "review_policy": {"mode": "view", "expires_after_seconds": None},
            },
        ),
        (
            FlowStepKind.STRUCTURED,
            {"instruction": "Ta fram fakta.", "example": _FACTS},
            {
                "output_type": "json",
                "output_contract": {
                    "type": "object",
                    "properties": {
                        "beslut": {"type": "string"},
                        "datum": {"type": "string"},
                    },
                    "required": ["beslut", "datum"],
                },
            },
        ),
        (
            FlowStepKind.AI,
            {"instruction": "Läs.", "input_bindings": _READ},
            {"input_bindings": _READ, "input_type": "text"},
        ),
        (
            FlowStepKind.STRUCTURED,
            {
                "instruction": "Ta fram fakta.",
                "example": _FACTS,
                "input_bindings": _READ,
                "review": {"mode": "edit"},
            },
            {
                "input_bindings": _READ,
                "review_policy": {"mode": "edit", "expires_after_seconds": None},
            },
        ),
        (
            FlowStepKind.DOCUMENT,
            {"input_bindings": _READ},
            {"output_mode": "render_verbatim", "input_bindings": _READ},
        ),
        (
            FlowStepKind.REVIEW,
            {"review": {"mode": "view"}},
            {"review_policy": {"mode": "view", "expires_after_seconds": None}},
        ),
        (
            FlowStepKind.TOOL,
            {"tool": _TOOL},
            {"input_source": "tool", "input_config": {"tool": _TOOL}},
        ),
        (
            FlowStepKind.COMPOSE,
            {"input_bindings": {"question": "Beslut: {{ step_1.output.text }}"}},
            {
                "output_mode": "compose_text",
                "input_bindings": {"question": "Beslut: {{ step_1.output.text }}"},
            },
        ),
        (
            FlowStepKind.DOCUMENT,
            {"format": "pdf"},
            {"output_mode": "render_verbatim", "output_type": "pdf"},
        ),
        (
            FlowStepKind.FETCH_HTTP,
            {"url": _URL, "http": {"response_format": "json"}},
            {"input_source": "http_get", "output_mode": "compose_text"},
        ),
        (
            FlowStepKind.SEND_HTTP,
            {
                "url": _URL,
                "http": {"auth": {"mode": "bearer_token"}, "timeout_seconds": 10},
                "instruction": "Lämna det vidare oförändrat.",
            },
            {"output_mode": "http_post"},
        ),
    ],
    ids=lambda value: value.value if isinstance(value, FlowStepKind) else None,
)
async def test_each_value_a_kind_takes_is_in_the_saved_step(
    kind: FlowStepKind,
    values: dict[str, Any],
    saved: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = _flow([_step(1)])

    step = await _added(flow, kind, values, monkeypatch)

    dumped = step.model_dump(mode="json")
    for column, value in saved.items():
        assert dumped[column] == value, column
    if kind is FlowStepKind.FETCH_HTTP:
        config = dumped["input_config"]
        assert (config["url"], config["response_format"], config["auth"]) == (
            _URL,
            "json",
            {"mode": "none"},
        )
    if kind is FlowStepKind.SEND_HTTP:
        config = dumped["output_config"]
        assert (config["url"], config["auth"]["mode"], config["timeout_seconds"]) == (
            _URL,
            "bearer_token",
            10,
        )


async def test_a_speaker_step_is_saved_with_its_choices_and_a_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow, _ = DRAFTS["transcript and speakers"]()
    flow = flow.model_copy(update={"steps": flow.steps[:1]})

    step = await _added(
        flow,
        FlowStepKind.SPEAKERS,
        {
            "participants_field": "deltagare",
            "speaker_count_field": "antal",
            "infer_names": True,
        },
        monkeypatch,
    )

    assert step.output_config == {
        "speaker_mapping": {
            "participants_field": "deltagare",
            "speaker_count_field": "antal",
            "infer_names": True,
        }
    }
    assert step.review_policy is not None


async def test_a_first_step_reads_an_upload_only_when_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = _flow([])

    text = await _added(empty, FlowStepKind.AI, {"instruction": "Läs."}, monkeypatch)
    upload = await _added(
        empty,
        FlowStepKind.AI,
        {"instruction": "Läs.", "upload": {"format": "document", "required": False}},
        monkeypatch,
    )

    assert (text.input_type, text.input_config) == ("text", None)
    assert upload.input_type == "document"
    assert upload.input_config == {
        "runtime_input": {
            "enabled": True,
            "required": False,
            "input_format": "document",
        }
    }


@pytest.mark.parametrize(
    ("kind", "needs"),
    [
        (FlowStepKind.AI, {"instruction": "Sammanfatta."}),
        (FlowStepKind.STRUCTURED, {"instruction": "Ta fram fakta.", "example": _FACTS}),
    ],
    ids=["ai", "structured"],
)
async def test_long_material_is_saved_beside_the_upload_it_is_given_with(
    kind: FlowStepKind, needs: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    digest = {"long_material": {"mode": "digest"}}

    first = await _added(
        _flow([]),
        kind,
        {**needs, "upload": {"format": "document"}, **digest},
        monkeypatch,
    )
    later = await _added(_flow([_step(1)]), kind, {**needs, **digest}, monkeypatch)

    # One input_config carries both values: neither replaces the other.
    assert first.input_type == "document"
    assert first.input_config == {**_DOCUMENT_UPLOADS, **digest}
    assert later.input_config == digest


def test_long_material_takes_only_the_modes_a_saved_step_takes() -> None:
    with pytest.raises(ValidationError):
        StepKindValues.model_validate({"long_material": {"mode": "summary"}})


def test_a_step_put_first_hands_over_from_its_final_shape() -> None:
    first = _step(1, input_type="json")
    flow = _flow([first])

    change = insertion_change(
        flow,
        FlowStepKind.STRUCTURED,
        position=1,
        values=StepKindValues(instruction="Ta fram fakta.", example=_FACTS),
    )

    # The new step gives json, which the old first step reads as it is.
    assert change.step_edits == ((first.id, {"input_source": "previous_step"}),)


@pytest.mark.parametrize(
    ("kind", "values", "message"),
    [
        (FlowStepKind.AI, {"instruction": "Läs.", "format": "pdf"}, "not use format"),
        (
            FlowStepKind.STRUCTURED,
            {"instruction": "Ta fram.", "example": _FACTS, "url": _URL},
            "not use url",
        ),
        (FlowStepKind.COMPOSE, {"review": {"mode": "edit"}}, "not use review"),
        (
            FlowStepKind.COMPOSE,
            {"long_material": {"mode": "digest"}},
            "not use long_material",
        ),
        (FlowStepKind.DOCUMENT, {"instruction": "Skriv."}, "not use instruction"),
        (FlowStepKind.TEMPLATE, {"instruction": "Fyll i."}, "not use instruction"),
        (FlowStepKind.TRANSCRIBE, {"instruction": "Skriv ut."}, "not use instruction"),
        (
            FlowStepKind.SPEAKERS,
            {"review": {"mode": "edit"}},
            "not use review",
        ),
        (FlowStepKind.REVIEW, {"instruction": "Granska."}, "not use instruction"),
        (
            FlowStepKind.FETCH_HTTP,
            {"url": _URL, "instruction": "Hämta."},
            "not use instruction",
        ),
        (FlowStepKind.TOOL, {"tool": _TOOL, "url": _URL}, "not use url"),
        (
            FlowStepKind.SEND_HTTP,
            {"url": _URL, "review": {"mode": "edit"}},
            "not use review",
        ),
        (FlowStepKind.STRUCTURED, {"instruction": "Ta fram."}, "needs example"),
        (FlowStepKind.SEND_HTTP, {}, "needs url"),
    ],
)
def test_a_value_the_kind_does_not_use_or_lacks_is_refused(
    kind: FlowStepKind, values: dict[str, Any], message: str
) -> None:
    with pytest.raises(BadRequestException) as refused:
        check_step_kind_values(kind, StepKindValues.model_validate(values))

    assert message in str(refused.value)
    assert refused.value.code == "flow_step_kind_values_invalid"


@pytest.mark.parametrize(
    "reads",
    [None, {"question": "Läs {{ step_1.output.text }}"}],
    ids=["after the step before", "with its own reads"],
)
async def test_an_upload_on_a_later_step_is_refused_by_the_save(
    reads: dict[str, str] | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    flow = _flow([_step(1)])
    values = StepKindValues.model_validate(
        {
            "instruction": "Läs.",
            "upload": {"format": "document"},
            **({"input_bindings": reads} if reads else {}),
        }
    )
    check_step_kind_values(FlowStepKind.AI, values)
    change = insertion_change(flow, FlowStepKind.AI, position=2, values=values)
    saved: list[Flow] = []

    refusal = await _save(flow, change, {}, monkeypatch, position=2, saved=saved)

    assert refusal is not None
    assert "only supported with input_source 'flow_input'" in str(refusal)
    assert saved == []


def test_the_value_tables_cover_every_kind_with_fields_the_values_have() -> None:
    kinds = set(FlowStepKind)
    assert set(STEP_KIND_DESCRIPTIONS) == kinds
    assert set(STEP_KIND_VALUES) == kinds
    assert set(STEP_KIND_REQUIRED_VALUES) <= kinds
    for kind, takes in STEP_KIND_VALUES.items():
        assert set(takes) <= set(StepKindValues.model_fields), kind
        assert set(STEP_KIND_REQUIRED_VALUES.get(kind, ())) <= set(takes), kind


def test_a_value_no_kind_has_is_refused_by_the_values_shape() -> None:
    with pytest.raises(ValidationError):
        StepKindValues.model_validate({"input_source": "flow_input"})


def test_settings_saved_with_the_step_keep_transcription_on() -> None:
    flow = _flow([_step(1)], metadata_json=_TRANSCRIBING)
    change = insertion_change(flow, FlowStepKind.TRANSCRIBE, position=1)

    # The settings replace wizard whole without the switch the step needs.
    update = editor_update(
        flow,
        change,
        expected_revision=flow.draft_revision,
        position=1,
        definition={"metadata_json": {"wizard": {"transcription_language": "sv"}}},
    )

    assert update.definition.metadata_json == {
        "wizard": {"transcription_language": "sv", "transcription_enabled": True}
    }


def test_a_word_step_takes_a_template_the_flow_has_or_waits_for_one() -> None:
    from eneo.flows.domain.step_kinds import step_kind_configuration

    template_id = uuid4()

    waiting = step_kind_configuration(FlowStepKind.TEMPLATE, previous_output_type=None)
    filled = step_kind_configuration(
        FlowStepKind.TEMPLATE,
        previous_output_type=None,
        values=StepKindValues(
            template_asset_id=template_id,
            bindings={"datum": "{{ flow_input.datum }}"},
        ),
    )

    assert waiting["output_config"] is None
    assert filled["output_config"] == {
        "template_asset_id": str(template_id),
        "bindings": {"datum": "{{ flow_input.datum }}"},
    }


def test_an_example_is_read_as_text_or_as_an_object() -> None:
    from eneo.flows.domain.step_kinds import step_kind_configuration

    as_text, as_object = (
        step_kind_configuration(
            FlowStepKind.STRUCTURED,
            previous_output_type=None,
            values=StepKindValues.model_validate({"example": example}),
        )
        for example in (_FACTS, {"beslut": "Bifall", "datum": "2026-11-11"})
    )

    assert as_text["output_contract"] == as_object["output_contract"]
    assert as_text["output_contract"] is not None
