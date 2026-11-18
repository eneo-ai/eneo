"""The helper chats' personas: the shared rules every target's persona
carries, and what the assistant's own fragment says it may do."""

from __future__ import annotations

from eneo.helper_chats.personas.assistant import (
    ASSISTANT_FRAGMENT,
    ASSISTANT_INSTRUCTIONS,
)
from eneo.helper_chats.personas.shared import HELPER_BASICS, PROMPT_WRITING


def _unwrapped(text: str) -> str:
    return " ".join(text.split())


def test_the_assistant_persona_is_the_basics_its_fragment_and_prompt_writing():
    for part in (HELPER_BASICS, ASSISTANT_FRAGMENT, PROMPT_WRITING):
        assert part in ASSISTANT_INSTRUCTIONS


def test_the_personas_use_no_long_dashes():
    for text in (HELPER_BASICS, ASSISTANT_FRAGMENT, PROMPT_WRITING):
        assert chr(0x2014) not in text
        assert chr(0x2013) not in text


def test_the_basics_keep_the_answer_brief_plain_and_in_the_persons_language():
    basics = _unwrapped(HELPER_BASICS)

    assert "Answer in the language the person writes in" in basics
    assert "Be brief" in basics
    assert "Never name your tools, field keys, ids, codes or other machinery" in (
        basics
    )
    assert 'In "Fråga" you read, explain and suggest, and change nothing' in basics
    assert "a proposal that the person applies with a click" in basics
    assert 'switches "Fråga" to "Redigera"' in basics
    assert "as a proposal where you can show one" in basics
    assert "Ask only when the answer changes what you do" in basics
    assert "with the question tool" in basics
    assert "never repeat one" in basics


def test_prompt_writing_has_no_protocol_of_its_own():
    """The chat's question tool asks, and the instructions are given in the
    answer; nothing is fenced or tagged for a client to parse."""
    assert "eneo-question" not in PROMPT_WRITING
    assert "```" not in PROMPT_WRITING
    writing = _unwrapped(PROMPT_WRITING)
    assert "first ask what the assistant will be used for" in writing
    assert "never from invented facts" in writing
    assert "When an organisation policy locks the instructions" in writing


def test_the_assistant_fragment_proposes_in_view_mode_and_changes_in_edit_mode():
    fragment = _unwrapped(ASSISTANT_FRAGMENT)

    assert 'In "Fråga", when the person wants one of these changed, show the' in (
        fragment
    )
    assert "a proposal with propose_changes" in fragment
    assert "do not also paste them into your answer" in fragment
    assert 'In "Redigera", make the change with update_assistant' in fragment
    assert "say in one sentence what you changed" in fragment
    assert "a short description in the person's language" in fragment
    assert "read_options before you suggest a choice" in fragment
    assert "never suggest changing it" in fragment


def test_the_assistant_fragment_names_a_published_assistant_once():
    fragment = _unwrapped(ASSISTANT_FRAGMENT)

    assert "applies at once for everyone who uses it" in fragment
    assert "Say so once, the first time" in fragment
    assert "not every time" in fragment


def test_the_assistant_fragment_sends_the_rest_to_the_editor():
    fragment = _unwrapped(ASSISTANT_FRAGMENT)

    assert "Everything else you cannot change, in either mode" in fragment
    assert "say where in the editor they change it" in fragment
