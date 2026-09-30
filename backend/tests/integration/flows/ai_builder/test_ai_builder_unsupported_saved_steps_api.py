"""Edit sessions on a saved flow the Builder can inspect but not edit.

The session answers with a typed not-editable outcome and pays for no edit
proposal; the same saved flow still takes the turns that propose nothing.
"""

from __future__ import annotations

import json
from typing import cast
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.database.tables.flow_tables import FlowSteps
from eneo.flows.ai_builder import ai_builder_planner as planner_module
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.prompts.api.prompt_models import PromptCreate
from tests.integration.flows.test_ai_builder_session_api_regressions import (
    _classifier_reading_nothing,
    _create_ai_builder_session,
    _create_space_with_planner_model,
    _make_flow_step,
    _make_llm_response,
    _route,
    _send_builder_message,
    _shown_instance,
    bearer_token,  # noqa: F401  (registers the fixture)
)

_CREDENTIAL = "sk-live-credential-looking-value"
_ROUTES = {
    "hosted_gpt": "openai/gpt-5.4",
    "hosted_gemma": "hosted_vllm/gemma4-31b-it",
}
_SHAPES: dict[str, dict[str, object]] = {
    "http_get_input": {
        "input_source": "http_get",
        "input_config": {
            "url": "https://example.org/a",
            "auth": {"mode": "bearer_token", "token": _CREDENTIAL},
        },
    },
    "image_input": {"input_type": "image"},
    "http_post_output": {
        "output_mode": "http_post",
        "output_type": "json",
        "output_config": {
            "url": "https://example.org/b",
            "auth": {"mode": "bearer_token", "token": _CREDENTIAL},
            "body": {"mode": "text_template", "template": "{{flow_input.text}}"},
        },
    },
}


async def _saved_flow(*, db_container, space_id: str, shape: str, mixed: bool):
    async with db_container() as container:
        flow_service = container.flow_service()
        flow = await flow_service.create_flow(
            space_id=UUID(space_id),
            name="Sparat flöde",
            description="Hämtar och sammanfattar.",
            steps=[],
        )
        assistants = []
        for name in ("first", "second", "third"):
            assistant, _ = await flow_service.create_flow_assistant(
                flow_id=flow.id, name=name
            )
            await flow_service.update_flow_assistant(
                flow_id=flow.id,
                assistant_id=assistant.id,
                update=AssistantUpdateCommand(
                    prompt=PromptCreate(text="Sammanfatta texten kort.")
                ),
            )
            assistants.append(assistant)
        unsupported = _make_flow_step(
            assistant_id=assistants[0].id,
            step_order=1,
            user_description="Hämta kurser",
            **{
                "input_type": "text",
                "input_source": (
                    "previous_step"
                    if mixed and shape == "http_post_output"
                    else "flow_input"
                ),
                # The flow service refuses image input; an older writer saved it.
                **({} if shape == "image_input" else _SHAPES[shape]),
            },
        )
        if not mixed:
            steps = [unsupported]
        else:
            authorable = [
                _make_flow_step(
                    assistant_id=assistants[index].id,
                    step_order=index + 1,
                    user_description=name,
                    input_source=(
                        "flow_input"
                        if index == 0 and shape == "http_post_output"
                        else "previous_step"
                    ),
                )
                for index, name in ((0, "Sammanfatta"), (1, "Skriv rapport"))
            ]
            # An HTTP delivery step is only valid last.
            steps = (
                [*authorable, unsupported.model_copy(update={"step_order": 3})]
                if shape == "http_post_output"
                else [
                    unsupported,
                    *(
                        step.model_copy(update={"step_order": step.step_order + 1})
                        for step in authorable
                    ),
                ]
            )
        flow = await flow_service.update_flow(flow_id=flow.id, steps=steps)
        if shape == "image_input":
            await container.session().execute(
                sa.update(FlowSteps)
                .where(
                    FlowSteps.flow_id == flow.id,
                    FlowSteps.step_order == 1,
                )
                .values(input_type="image")
            )
            flow = await flow_service.get_flow(flow.id)
        return flow


async def _drive_to_answer(
    *, client, token: str, session_id: str, edit_context
) -> tuple[list[dict[str, object]], bool, dict[str, object]]:
    """Answer what the server asks until a turn proposes or refuses.

    Like the web client, every send repeats the scope the session edits in.
    """

    message = "Förbättra instruktionerna i flödet."
    question_answer: dict[str, object] | None = None
    saw_requirements_card = False
    for _ in range(7):
        turn_id = uuid4()
        sent: dict[str, object] = {
            "message": message,
            "client_turn_id": turn_id,
            "question_answer": question_answer,
            "edit_context": edit_context,
        }
        events = await _send_builder_message(
            client=client,
            bearer_token=token,
            session_id=session_id,
            **sent,
        )
        summary = next(
            (e for e in events if e["event"] == "requirements_summary"), None
        )
        if summary is not None:
            saw_requirements_card = True
            message = ""
            question_answer = {
                "requirements_confirmed": True,
                "requirements_version": cast(dict, summary["data"])[
                    "requirements_version"
                ],
                **_shown_instance(events, "requirements_summary"),
                "ui_language": "sv",
            }
            continue
        question = next((e for e in events if e["event"] == "question"), None)
        if question is not None:
            data = cast(dict, question["data"])
            option = data["options"][0]
            message = option["label"]
            question_answer = {
                "question_id": data["question_id"],
                "selected_option_ids": [option["id"]],
                "selected_values": [option["id"]],
                **_shown_instance(events, "question"),
                "ui_language": "sv",
            }
            continue
        return events, saw_requirements_card, sent
    raise AssertionError("the session never reached a proposal or an answer")


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("route_name", sorted(_ROUTES))
@pytest.mark.parametrize(
    ("mixed", "scoped"),
    [(False, False), (True, True)],
    ids=["alone_whole_flow", "mixed_scoped_step"],
)
@pytest.mark.parametrize("shape", sorted(_SHAPES))
async def test_an_edit_on_a_saved_flow_the_builder_cannot_edit_is_answered_not_proposed(
    client,
    bearer_token,  # noqa: F811
    completion_model_factory,
    db_container,
    shape: str,
    mixed: bool,
    scoped: bool,
    route_name: str,
) -> None:
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name=f"Unsupported saved steps {shape} {mixed} {route_name}",
        planner_model_overrides={"max_input_tokens": 128_000},
        planner_model_is_only_space_model=True,
    )
    flow = await _saved_flow(
        db_container=db_container, space_id=space_id, shape=shape, mixed=mixed
    )
    edit_context = (
        {"kind": "saved_flow_step", "flow_step_id": str(flow.steps[1].id)}
        if scoped
        else None
    )
    proposal_provider = AsyncMock(return_value=_make_llm_response(content="unused"))

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
            new=proposal_provider,
        ),
        _classifier_reading_nothing(),
        patch(
            "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
            new=AsyncMock(
                return_value=_route(
                    model=_ROUTES[route_name], kwargs={"api_key": "sk-test"}
                )
            ),
        ),
        patch.object(planner_module.logger, "info") as planner_log,
    ):
        session_id = await _create_ai_builder_session(
            client=client,
            bearer_token=bearer_token,
            space_id=space_id,
            target_kind="edit",
            flow_id=str(flow.id),
        )
        events, saw_requirements_card, last_send = await _drive_to_answer(
            client=client,
            token=bearer_token,
            session_id=session_id,
            edit_context=edit_context,
        )
        calls_after_answer = proposal_provider.await_count

        # The same turn id replays the committed answer: no proposal-provider work and
        # no duplicate-spend acknowledgement.
        replay = await _send_builder_message(
            client=client, bearer_token=bearer_token, session_id=session_id, **last_send
        )

    names = [e["event"] for e in events]
    assert "error" not in names and "plan" not in names, names
    text = next(e for e in events if e["event"] == "text")
    affected_name = "Hämta kurser"
    answer_text = cast(dict, text["data"])["text"]
    assert f"`{affected_name}`" in answer_text
    # A scoped edit of a step the Builder can edit is also told that no edit
    # can be proposed while the other steps exist.
    assert ("föreslå ändringar i det här flödet" in answer_text) is scoped
    assert names[-1] == "done"
    assert proposal_provider.await_count == 0
    assert calls_after_answer == 0
    assert [e["event"] for e in replay] == ["done"]
    assert proposal_provider.await_count == 0
    if not scoped:
        # A whole-flow edit shows the requirements card first, as before.
        assert saw_requirements_card

    session = await client.get(
        f"/api/v1/flows/ai-builder/sessions/{session_id}",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert session.status_code == 200, session.text
    body = session.json()
    assert body["latest_turn"]["state"] == "committed"
    assert body["latest_turn"]["error"] is None
    async with db_container() as container:
        stored = await AIBuilderRepository(container.session()).get_session(
            session_id=UUID(session_id), tenant_id=flow.tenant_id
        )
    assistant = [m for m in stored.conversation if m.role == "assistant"][-1]
    assert (assistant.metadata or {})["non_plan_outcome"] == {
        "kind": "edit_blocked_by_unsupported_step",
        "required_action": "edit_in_step_editor",
        "affected": [affected_name],
        "affected_remaining": 0,
    }
    disclosed = json.dumps(
        [assistant.metadata, assistant.content, body["latest_turn"]], default=str
    ) + str(planner_log.call_args_list)
    assert _CREDENTIAL not in disclosed
    [refusal_log] = [
        call
        for call in planner_log.call_args_list
        if call.args[0].startswith("Saved flow has steps")
    ]
    assert refusal_log.kwargs["extra"]["steps"] == [
        {
            "step_order": 3 if mixed and shape == "http_post_output" else 1,
            "fields": dict([_FIELD_OF_SHAPE[shape]]),
        }
    ]


_FIELD_OF_SHAPE = {
    "http_get_input": ("input_source", "http_get"),
    "image_input": ("input_type", "image"),
    "http_post_output": ("output_mode", "http_post"),
}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_refused_session_keeps_the_reading_it_paid_for(
    client,
    bearer_token,  # noqa: F811
    completion_model_factory,
    db_container,
) -> None:
    """The refusal stores the reading like any answered turn, so later turns do
    not pay to read the same text again."""

    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="Refused session keeps its reading",
        planner_model_overrides={"max_input_tokens": 128_000},
        planner_model_is_only_space_model=True,
    )
    flow = await _saved_flow(
        db_container=db_container,
        space_id=space_id,
        shape="http_get_input",
        mixed=True,
    )
    edit_context = {"kind": "saved_flow_step", "flow_step_id": str(flow.steps[1].id)}
    follow_ups = ["Gör den kortare.", "Ändra stegets titel.", "Lägg till en rubrik."]

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
            new=AsyncMock(return_value=_make_llm_response(content="unused")),
        ),
        _classifier_reading_nothing() as classify,
        patch(
            "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
            new=AsyncMock(
                return_value=_route(
                    model=_ROUTES["hosted_gpt"], kwargs={"api_key": "sk-test"}
                )
            ),
        ),
    ):
        session_id = await _create_ai_builder_session(
            client=client,
            bearer_token=bearer_token,
            space_id=space_id,
            target_kind="edit",
            flow_id=str(flow.id),
        )
        events, _, _ = await _drive_to_answer(
            client=client,
            token=bearer_token,
            session_id=session_id,
            edit_context=edit_context,
        )
        assert "text" in [e["event"] for e in events]
        reads_before = classify.await_count
        for follow_up in follow_ups:
            refused = await _send_builder_message(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                message=follow_up,
                edit_context=edit_context,
            )
            assert "error" not in [e["event"] for e in refused]

    # One reading per new message, never one more for text already read.
    assert classify.await_count == reads_before + len(follow_ups)

    async with db_container() as container:
        stored = await AIBuilderRepository(container.session()).get_session(
            session_id=UUID(session_id), tenant_id=flow.tenant_id
        )
    by_text = {m.content: m for m in stored.conversation if m.role == "user"}
    for follow_up in follow_ups:
        metadata = by_text[follow_up].metadata or {}
        assert "slot_classification" in metadata, follow_up
        assert metadata.get("text_status") == "settled", follow_up
