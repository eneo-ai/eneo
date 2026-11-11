"""The flow chat's instructions carry the suggestion catalogue's authoring
rules, so a code cannot be added without its guidance reaching the chat, and
a chat left in edit mode returns to view mode after a pause."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from eneo.audit.domain.action_types import ActionType
from eneo.database.tables.flow_authoring_chats_table import FlowAuthoringChats
from eneo.flows.application import flow_authoring_chat
from eneo.flows.application.flow_authoring_chat import (
    AUTHORING_INSTRUCTIONS,
    starts_in_edit_mode,
    tool_runtime_capabilities,
)
from eneo.flows.domain.flow_suggestions import (
    FLOW_SUGGESTION_AUTHORING_RULES,
    FlowSuggestionCode,
)
from eneo.flows.enums import FlowInputSource, FlowOutputDelivery, FlowOutputMode
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.exceptions import BadRequestException
from eneo.mcp_servers.domain.capabilities import CapabilityAvailability


def _unwrapped(text: str) -> str:
    return " ".join(text.split())


def test_the_instructions_hold_every_authoring_rule() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    for code in FlowSuggestionCode:
        assert _unwrapped(FLOW_SUGGESTION_AUTHORING_RULES[code]) in instructions


def test_the_instructions_resolve_introduced_suggestions_in_the_same_turn() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "Design every step by these rules from the start" in instructions
    assert "introduced_suggestions" in instructions
    assert "Resolve each in the same turn" in instructions
    assert "unless the user explicitly asked for that shape" in instructions
    assert chr(0x2014) not in AUTHORING_INSTRUCTIONS


def test_the_instructions_turn_a_pasted_task_into_a_flow_instead_of_doing_it() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "you do not do the work a flow is for" in instructions
    assert "Never carry such a task out in the chat" in instructions
    assert "In edit mode, build it" in instructions
    assert "When edit mode is off, describe the steps" in instructions


def test_the_instructions_build_the_whole_flow_in_the_turn_that_asks() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "Build the whole flow in the turn that asks for it" in instructions
    assert "when one change is saved, go on to the next" in instructions
    # What waits for the person is named at the end, not waited for.
    assert "never stops the building: go on, and name it once" in instructions
    assert "ask it before you build, not between two steps" in instructions
    # The build is held against the request before it is called done.
    assert "read its overview once more and hold it against the request" in (
        instructions
    )
    assert "the text it gets is written by an AI step before it" in instructions
    assert "Each answer is in the draft as the person gave it" in instructions
    assert "Put right what is missing before you answer" in instructions
    assert "and the next change in the round after it" in instructions
    assert "build the rest of the flow first, then say that the person chooses" in (
        instructions
    )


def test_the_instructions_ask_one_shaping_question_at_a_time() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "Ask only where the answer changes the shape of the flow" in instructions
    assert "Ask one question at a time" in instructions
    assert (
        "Never ask what the flow, an uploaded file or an earlier answer already says"
        in instructions
    )
    assert "take a reasonable first option" in instructions
    assert (
        "Permission to send data anywhere or to start a run is never assumed"
        in instructions
    )
    assert "ask before it, every time" in instructions
    assert "instructions to follow, an example of what a run gets as input" in (
        instructions
    )


def test_the_instructions_offer_only_what_a_flow_can_do() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    # Every building block is named, so the model knows the whole list.
    for member in (*FlowInputSource, *FlowOutputMode, *FlowOutputDelivery):
        assert f"{member.value}:" in instructions
    assert "A result leaves a flow in these ways and no other" in instructions
    assert "There is no email, no messaging" in instructions
    assert "whatever words they use, say in one sentence" in instructions
    assert "Never offer it as a choice" in instructions
    assert "Put a choice in the flow's own words" in instructions
    assert "A choice is a complete answer, sent when it is clicked" in instructions
    assert (
        "read here in Eneo, or received by a system at an HTTPS address" in instructions
    )
    assert "A delivery step cannot be saved without its address" in instructions
    assert "ask for the address in plain words" in instructions
    assert "address left empty" not in instructions
    assert "ask in your reply in plain words, never with choices" in instructions
    assert "An answer already given is settled" in instructions


def test_the_instructions_say_each_pruned_rule_once() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    # What a flow cannot deliver is said where the building blocks are listed.
    assert instructions.count("There is no email") == 1
    assert "are never choices" not in instructions
    assert "never a product or service" not in instructions
    # A credential is kept out of the chat by the connection rules alone.
    assert instructions.count("Never ask for a key, token or password") == 1
    assert "Never ask for credentials" not in instructions
    # A typed answer is asked for in plain words once.
    assert instructions.count("never with choices") == 1
    assert "stands for typing it" not in instructions


def test_the_instructions_name_the_switch_to_redigera_in_the_uis_words() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert 'switches the button "Fråga" beside the send button to "Redigera"' in (
        instructions
    )
    assert "change nothing, say so in the first sentence" in instructions
    assert '"utkastet" or "ett utkast", never "draft"' in instructions
    assert "the first sentence of your answer says that nothing was changed" in (
        instructions
    )
    # HTTP or a named receiver already answers where the result goes.
    assert "the person has named no HTTP, address or receiving system" in (instructions)


def test_the_instructions_say_what_a_word_step_and_a_delivery_step_can_do() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "gets the value it reads as it is, word for word" in instructions
    assert "add an AI step before it that gives json" in instructions
    assert "A file attached in the chat cannot become a Word step's template" in (
        instructions
    )
    assert '("Ladda upp en Word-mall")' in instructions
    assert 'the body {"mode": "auto"}' in instructions
    assert 'runtime_input "required": true' in instructions


def test_a_new_chat_builds_an_empty_draft_and_only_reads_any_other_flow() -> None:
    assert starts_in_edit_mode(SimpleNamespace(steps=[], published_version=None))
    assert not starts_in_edit_mode(
        SimpleNamespace(steps=[object()], published_version=None)
    )
    assert not starts_in_edit_mode(SimpleNamespace(steps=[], published_version=1))


def test_the_instructions_explain_transcription_but_leave_its_choices() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "The source of the audio picks the model" in instructions
    assert (
        "transcription_model writes the text of uploaded and recorded" in instructions
    )
    assert "that text is the run's text, so the recording is not" in instructions
    assert "it writes no text of its own" in instructions
    assert "never write their ids" in instructions
    # What the space offers is read by name, and only that is offered.
    assert "read_flow says by name what the flow's space offers" in instructions
    assert "Offer only what is listed there" in instructions
    assert "say that an administrator adds it to the space" in instructions
    assert '"Ändra inställningar", in the Transkribering part' in instructions


def test_the_instructions_settle_the_speakers_of_a_recorded_conversation() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    # What the step is, in the tools' fields and in the editor's words.
    assert (
        'A step with output_mode speaker_mapping, "Granska transkript" in the '
        "editor, names them" in instructions
    )
    for setting, label in (
        ("participants_field", "Fält med deltagare"),
        ("infer_names", "Låt AI:n föreslå namn och roller"),
        ("speaker_count_field", "Fält med antal talare"),
    ):
        assert f'{setting} ("{label}")' in instructions
    assert (
        "The step needs a source of names: a participants field, infer_names "
        "true, or both" in instructions
    )
    assert "a prompt reads it as {{ step_N.output.text }}" in instructions
    # It asks before it builds, and only what the request leaves open.
    assert "how the speakers of a recorded conversation are named" in instructions
    assert "settle the speakers before you build it" in instructions
    assert "asking only what the person's text leaves open, one question at a" in (
        instructions
    )
    assert "Then build it without asking and say in a sentence what you chose" in (
        instructions
    )
    assert "gets no speaker step and no question" in instructions
    # Only a transcript the flow makes from audio has labels to name.
    assert "the step before it is always the one that transcribes" in instructions
    assert "A flow that receives a finished transcript, typed or as a file" in (
        instructions
    )
    assert "whether a run brings the recording or a finished transcript" in (
        instructions
    )
    # A space without a speaker service is not offered named speakers.
    assert "when transcription_offer lists no speaker service" in instructions
    assert "do not offer to name them as if it could" in instructions
    # The step is never saved without the run form field it reads.
    assert "the same add_step call gives the form its field in settings" in (
        instructions
    )
    # A wizard key is added without dropping the transcription choices.
    assert "wizard is replaced whole" in instructions
    assert "its other keys copied unchanged" in instructions


def test_the_instructions_account_for_what_blocks_publishing() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "lists under publish_blockers" in instructions
    assert "account for every blocker that is left" in instructions
    assert "Fix in the same turn what a setting fixes" in instructions
    assert "What only the person can do, say in one plain sentence each" in (
        instructions
    )
    # A blocker the person removes is never removed by rebuilding the step.
    assert (
        "Never make a blocker go away by changing what a step is for or by "
        "taking a step out" in instructions
    )
    assert "a Word step that waits for its template stays a Word step" in instructions
    assert (
        "Never call a flow ready to publish while publish_blocker_count is above zero"
        in instructions
    )


def test_the_instructions_take_a_contract_from_an_example() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "derive the step's contract from it with contract_from_example" in (
        instructions
    )
    assert "the example itself is not saved" in instructions
    assert "ask for one when the wanted result is structured" in instructions


def test_the_instructions_show_the_expected_result_without_doing_the_work() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "say in a few lines what its result will look like" in instructions
    assert "mark what is not saved yet as a proposal" in instructions
    assert "Use placeholders for content" in instructions
    assert "Describing the shape of the result this way is part of building" in (
        instructions
    )
    assert "filling it with content is doing the work the flow is for" in instructions
    assert "Explaining a run the person asks about" in instructions


def test_the_instructions_carry_a_change_to_the_steps_that_read_it() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "read its readers in read_flow" in instructions
    assert "in the same update_steps call" in instructions
    assert "Leave the steps that do not read it untouched" in instructions
    assert "read a step in full (section steps) before changing it" in instructions


def test_the_instructions_tell_a_runs_kinds_of_failure_apart() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "read it with read_run first" in instructions
    assert "A transient error never changes a prompt" in instructions
    assert "For content, follow the correction rules below" in instructions
    assert "call a token impact an estimate" in instructions
    assert "offer it only for a transient error" in instructions
    assert "call it only after a yes" in instructions
    assert "the way is a new run once it is published, not a retry" in instructions


def test_the_instructions_correct_content_in_the_run_or_in_the_instruction() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "correct this run's result, or change the instruction" in instructions
    assert "Offer the first only while the run waits for review" in instructions
    assert "a result of an ended run cannot be changed" in instructions
    assert "call review_run with action edit only after a yes" in instructions
    assert "never approve, reject or resume a review on your own" in instructions
    assert "corrected by the person in the run's own transcript" in instructions
    assert "this run stays as it is" in instructions
    assert "say that, and offer both" in instructions


def test_the_instructions_leave_unpublishing_to_the_person() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "you have no tool to unpublish it" in instructions
    assert 'the "Avpublicera" button at the top of the flow page' in instructions
    assert "only after the person has unpublished it in the editor" in instructions


def test_the_instructions_keep_every_secret_out_of_the_chat() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "Build everything but the secret" in instructions
    assert "Never ask for a key, token or password in the chat" in instructions
    assert "never put one in a tool argument" in instructions
    assert 'so its pill offers "Anslut tjänst"' in instructions
    assert "an administrator must add the server or grant it to the space" in (
        instructions
    )
    assert "Testing a connection is the person's action in the editor" in instructions


def test_the_instructions_declare_the_auth_mode_and_leave_the_credential_out() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert (
        'auth is {"mode": "none"} only for a service that asks for no credential'
        in (instructions)
    )
    assert "declare its mode with the credential left out" in instructions
    assert '{"mode": "api_key", "header_name": "X-API-Key"}' in instructions
    assert '{"mode": "basic_auth", "username": "..."}' in instructions
    assert 'A secret header is declared as {"name": "...", "secret": true}' in (
        instructions
    )
    assert "read_flow shows it as missing until then" in instructions
    # One rule for the mode: none of the earlier contradicting forms is left.
    assert 'Keep auth at {"mode": "none"}' not in instructions
    assert "never built with mode none" not in instructions


def test_the_instructions_leave_a_stored_credentials_config_to_the_editor() -> None:
    """The tools refuse any change to a config that holds a stored credential,
    so the chat says what to change in the editor instead of changing it."""
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert (
        "Once a credential is stored, the tools refuse any change to the config "
        "that holds it, the address included" in instructions
    )
    assert "the person changes it in the step in the editor" in instructions
    assert "A changed address keeps no stored credential" not in instructions


def test_the_instructions_describe_an_http_steps_whole_config() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert '"custom_headers": [{"name": "...", "value": "...", "secret": false}]' in (
        instructions
    )
    assert '"response_format": "text" or "json"' in instructions
    assert '"json_template" or "text_template", "template": "..."}' in instructions
    assert '{"mode": "none"}. The step decides the method' in instructions
    assert "there is no method key" in instructions
    assert "the address, the method" not in instructions


def test_the_instructions_rebase_a_stale_change_and_stop_after_two() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert f"(code {FlowApiErrorCode.STALE_REVISION.value}, with the draft's" in (
        instructions
    )
    assert "read the flow again with read_flow and make only your own change" in (
        instructions
    )
    assert "never restore a field the person changed meanwhile" in instructions
    assert "refused as stale twice in a row, stop and tell the person" in instructions
    assert "reload the current revision" not in instructions
    assert "Do not try to bypass it" not in instructions


def test_the_instructions_make_one_draft_change_per_round_of_tool_calls() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "make at most one call that changes the draft per round" in instructions
    assert "a change that reaches several steps goes in one update_steps call" in (
        instructions
    )


def test_the_instructions_leave_the_confirmation_to_the_chat() -> None:
    """The run, review and publish tools ask the person themselves, so the
    assistant calls them when asked, without a question of its own first, and
    reports a denied call as the person's no."""
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert (
        "(run_flow, retry_run, cancel_run, review_run, publish_flow) shows the "
        "person a confirmation in the chat before anything happens"
    ) in instructions
    assert "do not first ask, in words or with a question, whether to go ahead" in (
        instructions
    )
    assert "the person declined the confirmation or did not answer it" in instructions


def test_the_instructions_carry_what_the_tool_servers_notes_said() -> None:
    """Eneo's MCP client reads no server instructions, so the prompt says what
    the flow tools need beyond their own descriptions."""
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "they reach this flow only" in instructions
    assert "follow next_offset until it is null" in instructions
    assert 'input_config.long_material to {"mode": "digest"}' in instructions
    assert "partial coverage fails the step unless it has a review" in instructions
    assert "A change to input_config replaces it whole" in instructions
    assert "Name a step as @[<user_description>](step:<id>)" in instructions
    assert "the person's messages use the same forms" in instructions
    assert "or a change is refused because edit mode is off" in instructions


def test_the_chat_gets_the_tool_runtime_functions_its_space_offers_and_a_provider_serves():
    states = [
        CapabilityAvailability(purpose="file_analysis", available=True),
        CapabilityAvailability(purpose="file_creation", available=True),
        CapabilityAvailability(purpose="charts", available=False, reason="no_provider"),
        CapabilityAvailability(purpose="compute", available=True),
        CapabilityAvailability(purpose="web_search", available=True),
    ]
    # Charts has no ready provider, compute is not offered by the space, and
    # web search is not a tool runtime function: none of them is given.
    assert tool_runtime_capabilities(
        ["file_creation", "charts", "file_analysis", "web_search"], states
    ) == ["file_analysis", "file_creation"]
    assert tool_runtime_capabilities([], states) == []


async def test_a_change_to_a_published_flow_is_refused_before_anything_happens(
    monkeypatch,
) -> None:
    """The chat cannot unpublish a flow, so a draft change to a published one
    is refused with the one message that names the editor's action."""
    access = SimpleNamespace(flow=SimpleNamespace(published_version=2))
    monkeypatch.setattr(
        flow_authoring_chat, "require_flow_edit_access", AsyncMock(return_value=access)
    )
    chat = SimpleNamespace(editing=True, space_id=uuid4(), flow_id=uuid4())

    with pytest.raises(BadRequestException) as refused:
        await flow_authoring_chat.require_authoring_edit(MagicMock(), chat, draft=True)
    assert refused.value.code == "flow_published"
    assert '"Avpublicera" button' in str(refused.value)
    assert "Avpublicera för att ändra" not in str(refused.value)

    # Publishing itself is not a draft change and passes the same flow.
    await flow_authoring_chat.require_authoring_edit(MagicMock(), chat)


# --- Edit mode after a pause -------------------------------------------------


def _chat(*, editing: bool) -> FlowAuthoringChats:
    return FlowAuthoringChats(
        session_id=uuid4(),
        assistant_id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        user_id=uuid4(),
        flow_id=uuid4(),
        editing=editing,
        mode_changed_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )


def _container(*scalars: object) -> MagicMock:
    """A container whose session answers ``scalar`` with ``scalars`` in turn."""
    container = MagicMock()
    container.user.return_value = SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), username="anna", email="anna@example.org"
    )
    container.session.return_value.scalar = AsyncMock(side_effect=list(scalars))
    container.audit_service.return_value.log_async = AsyncMock()
    container.flow_service.return_value.get_flow = AsyncMock(
        return_value=SimpleNamespace(id=uuid4(), name="Ärendeflöde")
    )
    return container


def _idle(monkeypatch: pytest.MonkeyPatch, idle: bool) -> AsyncMock:
    measured = AsyncMock(return_value=idle)
    monkeypatch.setattr(flow_authoring_chat, "_idle_since_last_activity", measured)
    return measured


def _loads_without_access_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flow_authoring_chat, "require_flows_enabled", AsyncMock())
    monkeypatch.setattr(
        flow_authoring_chat, "require_flow_current_definition_access", AsyncMock()
    )
    monkeypatch.setattr(flow_authoring_chat, "scoped_request", MagicMock())


async def test_a_chat_loaded_after_a_pause_is_in_view_mode_and_cannot_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opening the chat and starting a turn both load it, so a chat left in
    edit mode comes back in view mode after the pause, audited as a mode
    change, and its tool calls are refused a change."""
    _loads_without_access_checks(monkeypatch)
    _idle(monkeypatch, True)
    chat = _chat(editing=True)
    paused_since = chat.mode_changed_at
    container = _container(chat, chat.session_id)

    loaded = await flow_authoring_chat.load_authoring_chat(
        container, session_id=chat.session_id
    )

    assert loaded is chat
    assert chat.editing is False
    # The pause still counts, so turning edit mode on starts a new conversation.
    assert chat.mode_changed_at == paused_since
    audit = container.audit_service.return_value.log_async.await_args.kwargs
    assert audit["action"] == ActionType.FLOW_AUTHORING_MODE_CHANGED
    assert audit["entity_id"] == chat.flow_id
    assert audit["metadata"]["extra"] == {
        "session_id": str(chat.session_id),
        "editing": False,
        "reason": "idle",
    }
    with pytest.raises(BadRequestException):
        await flow_authoring_chat.require_authoring_edit(container, chat)


async def test_view_mode_is_written_only_over_the_chat_as_it_was_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _idle(monkeypatch, True)
    chat = _chat(editing=True)
    container = _container(chat.session_id)

    await flow_authoring_chat._leave_edit_mode_after_pause(container, chat)

    update = container.session.return_value.scalar.await_args.args[0]
    sql = str(update.compile(dialect=postgresql.dialect()))
    assert "SET editing=" in sql
    assert "mode_changed_at" not in sql.split("WHERE")[0]
    where = sql.split("WHERE")[1]
    assert "flow_authoring_chats.session_id =" in where
    assert "flow_authoring_chats.tenant_id =" in where
    assert "flow_authoring_chats.editing IS true" in where
    assert "flow_authoring_chats.mode_changed_at IS NOT DISTINCT FROM" in where


async def test_a_mode_change_saved_meanwhile_is_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _idle(monkeypatch, True)
    chat = _chat(editing=True)
    # The guarded update matched no row: the chat changed since it was read.
    container = _container(None)

    await flow_authoring_chat._leave_edit_mode_after_pause(container, chat)

    assert chat.editing is True
    container.audit_service.return_value.log_async.assert_not_awaited()


async def test_edit_mode_within_the_pause_is_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _idle(monkeypatch, False)
    chat = _chat(editing=True)
    container = _container()

    await flow_authoring_chat._leave_edit_mode_after_pause(container, chat)

    assert chat.editing is True
    container.session.return_value.scalar.assert_not_awaited()
    container.audit_service.return_value.log_async.assert_not_awaited()


async def test_a_chat_in_view_mode_is_not_measured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    measured = _idle(monkeypatch, True)
    chat = _chat(editing=False)
    container = _container()

    await flow_authoring_chat._leave_edit_mode_after_pause(container, chat)

    measured.assert_not_awaited()
    container.audit_service.return_value.log_async.assert_not_awaited()
