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
    step_kind_answer,
)
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.domain.flow_run_retention_policy import (
    FlowRunRetentionContributors,
    FlowRunRetentionOff,
)
from eneo.flows.domain.step_kinds import FlowStepKind
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
) -> BadRequestException | ValidationError | None:
    """The editor's save of ``change``: its refusal, or None when it saves."""
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
            flow, change, position=position, step_id=step_id, name="Added step"
        )
        await flow_authoring_operations.apply_editor_update(
            flow.require_persisted_id(),
            SimpleNamespace(state=SimpleNamespace()),  # type: ignore[arg-type]
            update,
            container,
        )
    except (BadRequestException, ValidationError) as exc:
        return exc
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
