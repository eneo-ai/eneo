"""A turn whose model requests left part of the user's material out says so.

The coverage rides on the turn's own user message: the stream's `coverage`
event carries the value the turn stored, and a reload shows the same value.
"""

from __future__ import annotations

import random
from contextlib import nullcontext
from typing import Any, cast
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from litellm.exceptions import BadRequestError
from sqlalchemy import delete, select, update

from eneo.completion_models.domain.model_capacity import ModelCapacity
from eneo.database.tables.flow_tables import BuilderSessions
from eneo.database.tables.mcp_server_table import MCPServers, MCPServerTools
from eneo.flows.ai_builder import ai_builder_repo
from eneo.flows.ai_builder.ai_builder_conversation_compaction import (
    MAX_SESSION_CONVERSATION_BYTES,
    conversation_serialized_size_bytes,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    turn_coverage_from_metadata,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from eneo.flows.ai_builder.ai_builder_settings import AIBuilderRequestBudget
from eneo.flows.ai_builder.ai_builder_turn_coverage import ProposalPromptCut
from eneo.flows.ai_builder.planning_state import PlanningState
from tests.integration.flows.ai_builder.test_ai_builder_space_tool_catalog import (
    _saved_flow_id,
    _seed_space_tools,
)
from tests.integration.flows.ai_builder.test_ai_builder_unsupported_saved_steps_api import (
    _drive_to_answer,
)
from tests.integration.flows.test_ai_builder_session_api_regressions import (
    _builder_event_outline,
    _claim_session_send_turn,
    _classifier_reading_nothing,
    _create_ai_builder_session,
    _create_space_with_planner_model,
    _make_llm_response,
    _reading_nothing_response,
    _route,
    _send_builder_message,
    _upload_reference_file,
    bearer_token,  # noqa: F401  (registers the fixture)
)

_RNG = random.Random(19)


def _longer_than_the_model_window() -> str:
    # Distinct words keep the token count near the word count, so the text is
    # far past a 32k window whichever tokenizer measures it.
    return " ".join(f"ord{_RNG.randrange(10**6)}" for _ in range(20_000))


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("turn", ["proposal_rejected", "message_unread"])
async def test_a_turn_that_left_material_out_streams_and_stores_one_coverage(
    client,
    bearer_token,  # noqa: F811
    completion_model_factory,
    db_container,
    turn: str,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name=f"AI Builder turn coverage {turn}",
        planner_model_overrides={"max_input_tokens": 32_000},
        planner_model_is_only_space_model=True,
    )
    session_id = await _create_ai_builder_session(
        client=client, bearer_token=bearer_token, space_id=space_id
    )
    if turn == "proposal_rejected":
        # Two older answers no request can hold, then the questions the server
        # asks: the proposal fit evicts the two, oldest first.
        earlier = [
            ConversationMessage(
                role="assistant", content=_longer_than_the_model_window()
            ),
            ConversationMessage(
                role="assistant", content=_longer_than_the_model_window()
            ),
        ]
        provider = AsyncMock(
            side_effect=BadRequestError("rejected", model="m", llm_provider="p")
        )
    else:
        # The reading keeps the new message whole and has room for only part
        # of the older one; its reply is empty, so the message stays unread.
        earlier = [
            ConversationMessage(role="user", content=_longer_than_the_model_window())
        ]
        provider = AsyncMock(return_value=_make_llm_response(content=""))
    async with db_container() as container:
        await container.session().execute(
            update(BuilderSessions)
            .where(BuilderSessions.id == UUID(session_id))
            .values(conversation=[m.model_dump(mode="json") for m in earlier])
        )

    with (
        _classifier_reading_nothing() if turn == "proposal_rejected" else nullcontext(),
        patch(
            "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion", new=provider
        ),
        patch(
            "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
            new=AsyncMock(return_value=_route(kwargs={"api_key": "sk-test"})),
        ),
    ):
        events, _, _ = await _drive_to_answer(
            client=client, token=bearer_token, session_id=session_id, edit_context=None
        )

    # Mutant: the event is sent before the error is stored, or not at all.
    assert [e["event"] for e in events if e["event"] != "status"] == [
        "error",
        "coverage",
        "done",
    ], _builder_event_outline(events)
    live = cast(
        dict[str, Any], next(e["data"] for e in events if e["event"] == "coverage")
    )

    reloaded = await client.get(
        f"/api/v1/flows/ai-builder/sessions/{session_id}",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert reloaded.status_code == 200, reloaded.text
    session = reloaded.json()
    turn_message_id = session["latest_turn"]["user_message_id"]
    by_id = {message["message_id"]: message for message in session["conversation"]}
    # Mutant: the coverage is not stored with the turn, or on another message.
    assert live == {
        "message_id": turn_message_id,
        "coverage": by_id[turn_message_id]["coverage"],
    }
    assert [
        message["coverage"]
        for message in session["conversation"]
        if message["message_id"] != turn_message_id
    ] == [None] * (len(session["conversation"]) - 1)

    (note,) = live["coverage"]["notes"]
    if turn == "proposal_rejected":
        assert session["latest_turn"]["error"]["code"] == "planner_upstream_error"
        # Mutant: the dropped count is taken from the kept messages.
        assert {key: note[key] for key in ("stage", "material", "omitted")} == {
            "stage": "proposal",
            "material": "history_messages",
            "omitted": 2,
        }
        assert note["total"] > 2
        assert (note["shortened"], note["reasons"]) == (0, ["model_room"])
    else:
        assert session["latest_turn"]["error"]["code"] == (
            "classification_unreadable_reply"
        )
        # The older message is cut or dropped by the capacity fit, never both.
        assert {
            key: note[key] for key in ("stage", "material", "total", "reasons")
        } == {
            "stage": "classification",
            "material": "classification_sources",
            "total": 2,
            "reasons": ["model_room"],
        }
        assert note["omitted"] + note["shortened"] == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_turn_notes_the_attached_file_and_tools_its_requests_could_not_carry(
    client,
    bearer_token,  # noqa: F811
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name=f"AI Builder turn coverage files {uuid4().hex[:6]}",
        planner_model_overrides={"max_input_tokens": 32_000},
        planner_model_is_only_space_model=True,
    )
    tool_id = await _seed_space_tools(db_container, UUID(space_id))
    flow_id = await _saved_flow_id(db_container, UUID(space_id))
    session_id = await _create_ai_builder_session(
        client=client,
        bearer_token=bearer_token,
        space_id=space_id,
        target_kind="edit",
        flow_id=flow_id,
    )
    file_id = await _upload_reference_file(
        client=client,
        bearer_token=bearer_token,
        content=_longer_than_the_model_window().encode(),
    )

    async def provider(**kwargs: object) -> object:
        # The reading finds nothing; the proposal request is refused.
        if "tools" in kwargs:
            raise BadRequestError("rejected", model="m", llm_provider="p")
        return _reading_nothing_response()

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
            new=AsyncMock(side_effect=provider),
        ),
        patch(
            "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
            new=AsyncMock(return_value=_route(kwargs={"api_key": "sk-test"})),
        ),
    ):
        first = await _send_builder_message(
            client=client,
            bearer_token=bearer_token,
            session_id=session_id,
            message="Förbättra instruktionerna i flödet.",
            file_ids=[file_id],
        )
        last, _, _ = await _drive_to_answer(
            client=client, token=bearer_token, session_id=session_id, edit_context=None
        )
    reloaded = await client.get(
        f"/api/v1/flows/ai-builder/sessions/{session_id}",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert reloaded.status_code == 200, reloaded.text
    async with db_container() as container:
        await container.session().execute(
            delete(MCPServers).where(
                MCPServers.id
                == select(MCPServerTools.mcp_server_id)
                .where(MCPServerTools.id == tool_id)
                .scalar_subquery()
            )
        )
    stored = {
        message["message_id"]: message["coverage"]
        for message in reloaded.json()["conversation"]
    }
    # The first turn's reading sent the file; a later turn's reading of the
    # same messages is answered from the cache and sends none.
    streamed = [
        cast(
            dict[str, Any], next(e["data"] for e in events if e["event"] == "coverage")
        )
        for events in (first, last)
    ]
    # Mutant: a note kind the turn stores is not the one it streams.
    for live in streamed:
        assert live["coverage"] == stored[live["message_id"]]
    notes = {
        (note["stage"], note["material"]): note
        for live in streamed
        for note in live["coverage"]["notes"]
    }
    file = {
        "kind": "count",
        "total": 1,
        "omitted": 0,
        "shortened": 1,
        "reasons": ["model_room"],
    }
    tools = {**file, "material": "usable_tools", "total": 2, "omitted": 2}
    # Mutants: the reading's or the proposal's request does not report the
    # attached file it carried in part; the attachment, fitted first, left
    # the space's two usable tools no room and that goes unsaid.
    assert [
        notes.get(key)
        for key in (
            ("classification", "attachment_files"),
            ("proposal", "attachment_files"),
            ("proposal", "usable_tools"),
        )
    ] == [
        {**file, "stage": "classification", "material": "attachment_files"},
        {**file, "stage": "proposal", "material": "attachment_files"},
        {**tools, "stage": "proposal", "shortened": 0},
    ]


async def _session_with_a_turn_that_left_history_out(
    *, client, token: str, completion_model_factory, db_container, repo, user
) -> SessionSendTurn:
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder turn coverage store",
    )
    session = await repo.create_session(
        tenant_id=user.tenant_id,
        space_id=UUID(space_id),
        actor_user_id=user.id,
        target_kind=TargetKind.CREATE,
        flow_id=None,
    )
    turn = await _claim_session_send_turn(
        repo=repo, session_id=session.id, tenant_id=user.tenant_id
    )
    turn.coverage.prepare_proposal(ProposalPromptCut(history_groups_left_out=1))
    budget = AIBuilderRequestBudget(
        capacity=ModelCapacity(100_000, 1_000),
        safety_buffer_tokens=0,
        timeout_seconds=30.0,
    ).plan(required_input_tokens=1)
    assert budget is not None
    turn.coverage.record_proposal_call(
        history_in_request=1, history_sent=1, request_budget=budget
    )
    return turn


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_committed_turn_builds_its_state_from_the_conversation_it_stores(
    client,
    bearer_token,  # noqa: F811
    completion_model_factory,
    db_container,
):
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        turn = await _session_with_a_turn_that_left_history_out(
            client=client,
            token=bearer_token,
            completion_model_factory=completion_model_factory,
            db_container=db_container,
            repo=repo,
            user=user,
        )
        stored = (
            await repo.get_session(session_id=turn.session_id, tenant_id=user.tenant_id)
        ).conversation
        answer = ConversationMessage(role="assistant", content="Hej")
        earlier = [
            ConversationMessage(role="assistant", content="a" * 25_000)
            for _ in range(40)
        ]
        # A conversation the turn's answer still fits under the byte cap, and
        # the coverage key alone would push over it.
        room = MAX_SESSION_CONVERSATION_BYTES - conversation_serialized_size_bytes(
            [*earlier, *stored, answer]
        )
        earlier[0] = earlier[0].model_copy(
            update={"content": earlier[0].content + "x" * (room - 100)}
        )
        await repo.session.execute(
            update(BuilderSessions)
            .where(BuilderSessions.id == turn.session_id)
            .values(
                conversation=[m.model_dump(mode="json") for m in [*earlier, *stored]]
            )
        )

        with patch.object(
            ai_builder_repo,
            "semantic_conversation",
            wraps=ai_builder_repo.semantic_conversation,
        ) as read_for_state:
            await repo.commit_turn(
                turn=turn, new_messages=[answer], planning_state=PlanningState.empty()
            )
        kept = (
            await repo.get_session(session_id=turn.session_id, tenant_id=user.tenant_id)
        ).conversation

    # Mutant: the key is added after the state was saved, and that write's
    # compaction drops a message the state was built from.
    assert [m.message_id for m in read_for_state.call_args.args[0]] == [
        m.message_id for m in kept
    ]
    assert turn_coverage_from_metadata(kept[-2].metadata) == turn.coverage.summary()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("ends_with", ["commit_turn", "completion_only"])
async def test_a_turn_writes_its_coverage_once(
    client,
    bearer_token,  # noqa: F811
    completion_model_factory,
    db_container,
    ends_with: str,
):
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        turn = await _session_with_a_turn_that_left_history_out(
            client=client,
            token=bearer_token,
            completion_model_factory=completion_model_factory,
            db_container=db_container,
            repo=repo,
            user=user,
        )
        with patch.object(
            repo, "append_session_messages", wraps=repo.append_session_messages
        ) as writes:
            if ends_with == "commit_turn":
                await repo.commit_turn(
                    turn=turn,
                    new_messages=[ConversationMessage(role="assistant", content="Hej")],
                    planning_state=PlanningState.empty(),
                )
            else:
                await repo.complete_session_turn(turn=turn)
            # Paths that complete the turn a second time, with the same value.
            await repo.complete_session_turn(turn=turn)
        stored = await repo.get_session(
            session_id=turn.session_id, tenant_id=user.tenant_id
        )

    # Mutant: every completion rewrites the conversation, or a commit stores
    # the key in a write of its own.
    assert writes.await_count == 1
    (user_message,) = [m for m in stored.conversation if m.role == "user"]
    assert turn_coverage_from_metadata(user_message.metadata) == turn.coverage.summary()
