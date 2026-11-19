"""The helper chats' personas: the shared rules every target's persona
carries, what the assistant's own fragment says it may do, and the note that
ends each turn's instructions."""

from __future__ import annotations

import re

import pytest

from eneo.helper_chats.personas.assistant import (
    ASSISTANT_FRAGMENT,
    ASSISTANT_INSTRUCTIONS,
    SETTING_REFERENCE_KEYS,
    SETTING_REFERENCE_PARAGRAPH,
)
from eneo.helper_chats.personas.shared import (
    ASKING_NOW,
    EDITING_NOW,
    HELPER_BASICS,
    PROMPT_WRITING,
    PROPOSING,
    WITHOUT_TOOLS,
    WITHOUT_TOOLS_NOW,
    turn_note,
)


def _unwrapped(text: str) -> str:
    return " ".join(text.split())


def _names_a_mode(text: str) -> bool:
    return re.search(r"\bmodes?\b", text) is not None


def test_the_assistant_persona_is_the_basics_its_fragment_and_prompt_writing():
    for part in (
        HELPER_BASICS,
        ASSISTANT_FRAGMENT,
        SETTING_REFERENCE_PARAGRAPH,
        PROMPT_WRITING,
    ):
        assert part in ASSISTANT_INSTRUCTIONS


def test_the_personas_use_no_long_dashes():
    for text in (
        HELPER_BASICS,
        ASSISTANT_FRAGMENT,
        SETTING_REFERENCE_PARAGRAPH,
        PROMPT_WRITING,
        EDITING_NOW,
        ASKING_NOW,
        WITHOUT_TOOLS_NOW,
        PROPOSING,
        WITHOUT_TOOLS,
    ):
        assert chr(0x2014) not in text
        assert chr(0x2013) not in text


def test_the_basics_keep_the_answer_brief_plain_and_in_the_persons_language():
    basics = _unwrapped(HELPER_BASICS)

    assert "Answer in the language the person writes in" in basics
    assert "Be brief" in basics
    assert "Never name your tools, field keys, ids, codes or other machinery" in (
        basics
    )
    assert (
        "When a change or a proposal is refused, the first sentence says that "
        "nothing was changed and what stands in the way"
    ) in basics
    assert "Ask only when the answer changes what you do" in basics
    assert "with the question tool" in basics
    assert "never repeat one" in basics


def test_the_basics_say_nothing_about_modes():
    basics = _unwrapped(HELPER_BASICS)

    assert not _names_a_mode(basics)
    assert '"Fråga"' not in basics
    assert '"Redigera"' not in basics


def test_in_redigera_the_note_says_so_and_that_the_change_is_made():
    note = turn_note(has_modes=True, editing=True, can_call_tools=True)

    assert note == EDITING_NOW
    assert note.startswith('The chat is in "Redigera" now')
    assert "you can change what this chat is about with your tools" in note
    assert "make the changes the person asks for" in note
    assert "Do not tell the person to switch modes" in note


def test_in_fraga_the_note_says_nothing_changes_and_how_to_have_it_made():
    note = turn_note(has_modes=True, editing=False, can_call_tools=True)

    assert note == ASKING_NOW
    assert note.startswith('The chat is in "Fråga" now')
    assert "you cannot change what this chat is about this turn" in note
    assert "the tools that change it are not offered" in note
    assert "as a proposal where you can show one" in note
    assert 'they can switch to "Redigera" to have it made' in note


@pytest.mark.parametrize("editing", [True, False])
def test_without_tools_the_note_never_sends_the_person_to_another_mode(
    editing: bool,
):
    note = turn_note(has_modes=True, editing=editing, can_call_tools=False)

    assert note == WITHOUT_TOOLS_NOW
    assert "You have no tools this turn, whichever mode the chat is in" in note
    assert "you can neither read nor change what this chat is about" in note
    assert "do not tell them to switch modes" in note
    assert '"Redigera"' not in note


@pytest.mark.parametrize("editing", [True, False])
def test_on_a_target_without_modes_the_note_has_each_change_proposed_with_the_tool(
    editing: bool,
):
    note = turn_note(has_modes=False, editing=editing, can_call_tools=True)

    assert note == PROPOSING
    assert "propose_changes" in note
    assert "nothing is saved before they press it" in note
    # A change put in words is no proposal: only the tool's call gives one.
    assert "A change you only describe in words gives them nothing to approve" in (note)
    assert "never announce or describe a proposal you have not made with the tool" in (
        note
    )
    assert "never say that you changed something" in note
    # The last thing the turn's instructions say is to call the tool.
    last = note.rstrip(".").rsplit(". ", 1)[-1]
    assert last.startswith("When the person asks for a change, call propose_changes")


@pytest.mark.parametrize("editing", [True, False])
def test_on_a_target_without_modes_a_model_without_tools_is_told_so(editing: bool):
    note = turn_note(has_modes=False, editing=editing, can_call_tools=False)

    assert note == WITHOUT_TOOLS
    assert "You have no tools this turn" in note
    assert "nor propose a change to it" in note


def test_a_note_on_a_target_without_modes_names_no_mode():
    for note in (PROPOSING, WITHOUT_TOOLS):
        assert not _names_a_mode(note)
        assert '"Fråga"' not in note
        assert '"Redigera"' not in note


def test_each_note_is_one_paragraph_and_only_the_proposal_note_names_a_tool():
    for note in (EDITING_NOW, ASKING_NOW, WITHOUT_TOOLS_NOW, PROPOSING, WITHOUT_TOOLS):
        assert "\n" not in note
    for note in (EDITING_NOW, ASKING_NOW, WITHOUT_TOOLS_NOW, WITHOUT_TOOLS):
        assert "_" not in note
    assert set(re.findall(r"\b\w*_\w*\b", PROPOSING)) == {"propose_changes"}


def test_prompt_writing_has_no_protocol_of_its_own():
    """The chat's question tool asks, and the instructions are given in the
    answer; nothing is fenced or tagged for a client to parse."""
    assert "eneo-question" not in PROMPT_WRITING
    assert "```" not in PROMPT_WRITING
    writing = _unwrapped(PROMPT_WRITING)
    assert "first ask what the assistant will be used for" in writing
    assert "never from invented facts" in writing
    assert "When an organisation policy locks the instructions" in writing


def test_the_assistant_fragment_shows_every_change_as_a_proposal_to_approve():
    fragment = _unwrapped(ASSISTANT_FRAGMENT)

    assert (
        "When the person wants one of these changed, call propose_changes with "
        "the change."
    ) in fragment
    # Words are no proposal: only the call gives the person one to approve.
    assert (
        "a change you describe in words is not a proposal and gives them nothing "
        "to approve, so never write that you propose a change you have not made "
        "with the tool"
    ) in fragment
    assert "Nothing is saved until the person applies the proposal" in fragment
    assert "never say that you changed something" in fragment
    # What it says of the proposal follows the call.
    assert (
        "Once the call has returned, say in a sentence or two what the proposal "
        "changes and why"
    ) in fragment
    assert "say what you propose" not in fragment
    # A change that does not build on the current value needs no read first.
    assert "such as a new name, needs no read first" in fragment
    assert "do not also paste them into your answer" in fragment
    assert (
        "When a proposal changes the instructions, give it a short description in "
        "the person's language"
    ) in fragment
    assert "once the proposal is applied, it shows in the instructions' version" in (
        fragment
    )
    assert "read_options before you suggest a choice" in fragment
    assert "never suggest changing it" in fragment


def test_the_assistant_persona_names_no_mode_and_no_direct_change():
    instructions = _unwrapped(ASSISTANT_INSTRUCTIONS)

    assert '"Fråga"' not in instructions
    assert '"Redigera"' not in instructions
    assert "edit mode" not in instructions
    assert "never tell the person to switch to another mode or name one" in (
        instructions
    )


def test_the_assistant_fragment_names_a_published_assistant_once():
    fragment = _unwrapped(ASSISTANT_FRAGMENT)

    assert "applies for everyone who uses it as soon as the person applies it" in (
        fragment
    )
    assert "Say so once, the first time you propose a change" in fragment
    assert "not every time" in fragment


def test_the_assistant_fragment_sends_the_rest_to_the_editor():
    fragment = _unwrapped(ASSISTANT_FRAGMENT)

    assert "Everything else you can neither change nor propose" in fragment
    assert "say where in the editor they change it" in fragment


def test_the_assistant_fragment_names_every_setting_the_chat_changes():
    fragment = _unwrapped(ASSISTANT_FRAGMENT)

    assert (
        "You can propose changes to the name, the description, the instructions, "
        "the chat model and its settings, the knowledge and the ranking of its "
        "results, the knowledge mode, how files uploaded in a chat are handled, "
        "the MCP servers and their tools, the functions, the document template, "
        "how long conversations are kept and whether insights are on."
    ) in fragment
    assert "name only what changes; the rest stays" in fragment
    assert "sources on different ones cannot be combined" in fragment
    assert (
        "Everything else you can neither change nor propose: attachments, skills, "
        "the icon, API keys, the web widget, conversation logging, and moving or "
        "deleting the assistant."
    ) in fragment


def test_the_assistant_fragment_suggests_only_what_the_person_may_change():
    fragment = _unwrapped(ASSISTANT_FRAGMENT)

    assert "Suggest only what the person may change" in fragment
    assert "names what their role does not let them change" in fragment
    assert "Never propose those; say who changes them" in fragment
    assert "or that a personal space does not use them" in fragment


def test_the_assistant_fragment_explains_the_editors_rules_instead_of_working_around():
    fragment = _unwrapped(ASSISTANT_FRAGMENT)

    assert "Knowledge and MCP servers are not combined on one assistant" in fragment
    assert (
        "MCP servers, their tools and functions are turned on only while the chat "
        "model can use tools"
    ) in fragment
    assert "read_assistant says when one of these rules stands in the way" in fragment
    assert (
        "Then do not propose around it: explain the rule and what the person can "
        "do instead, such as removing the MCP servers or choosing a model that can "
        "use tools, and propose that only when they want it."
    ) in fragment


def test_publishing_and_unpublishing_ask_the_person_with_their_own_approval():
    fragment = _unwrapped(ASSISTANT_FRAGMENT)

    assert (
        "Publishing and unpublishing are not proposals: each asks the person "
        "first, with an approval of its own."
    ) in fragment
    assert "Only when they ask for it, call publish_assistant" in fragment
    assert "nothing happens until they do" in fragment
    assert "do not repeat it unless they ask again" in fragment
    assert "They can also publish or unpublish under Publicering." in fragment


def test_earlier_versions_of_the_instructions_can_be_read():
    fragment = _unwrapped(ASSISTANT_FRAGMENT)

    assert "Earlier versions of the instructions are kept" in fragment
    assert "read_prompt_history reads them" in fragment
    assert "bringing one back is a proposal like any other" in fragment


# The same list, in the same order, as SETTING_REFERENCE_KEYS in the editor
# (frontend/apps/web-next/src/features/assistants/editor/setting-references.ts),
# whose test holds it to this one: change both together.
EDITOR_REFERENCE_KEYS = (
    "name",
    "description",
    "prompt",
    "knowledge_mode",
    "inline_file_text",
    "knowledge",
    "rerank_model_id",
    "mcp_servers",
    "attachments",
    "completion_model",
    "completion_model_kwargs",
    "completion_model_kwargs.reasoning_effort",
    "completion_model_kwargs.verbosity",
    "completion_model_kwargs.top_p",
    "completion_model_kwargs.presence_penalty",
    "completion_model_kwargs.frequency_penalty",
    "completion_model_kwargs.top_k",
    "enabled_capabilities",
    "document_template",
    "data_retention_days",
    "published",
    "insight_enabled",
    "section:general",
    "section:instructions",
    "section:knowledge",
    "section:skills",
    "section:mcp",
    "section:attachments",
    "section:ai",
    "section:capabilities",
    "section:security",
    "section:api-keys",
    "section:widget",
    "section:publishing",
)


def test_setting_references_name_the_editors_keys():
    assert SETTING_REFERENCE_KEYS == EDITOR_REFERENCE_KEYS


def test_the_persona_explains_setting_references_and_lists_every_key():
    paragraph = _unwrapped(SETTING_REFERENCE_PARAGRAPH)

    assert "The person may point at a setting or a part of the editor as" in paragraph
    assert "@[name](setting:key)" in paragraph
    assert "it means that setting or part as the form shows it now" in paragraph
    assert "you may write it the same way, with the name the editor shows" in (
        paragraph
    )
    assert "one of the keys below" in paragraph
    assert "never shows the key" in paragraph
    assert "Use only these keys" in paragraph
    for key in EDITOR_REFERENCE_KEYS:
        assert f"\n- {key}: " in SETTING_REFERENCE_PARAGRAPH
