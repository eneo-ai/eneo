"""The helper chats' personas: the shared rules every target's persona
carries, and what the assistant's own fragment says it may do."""

from __future__ import annotations

from eneo.helper_chats.personas.assistant import (
    ASSISTANT_FRAGMENT,
    ASSISTANT_INSTRUCTIONS,
    SETTING_REFERENCE_KEYS,
    SETTING_REFERENCE_PARAGRAPH,
)
from eneo.helper_chats.personas.shared import HELPER_BASICS, PROMPT_WRITING


def _unwrapped(text: str) -> str:
    return " ".join(text.split())


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


def test_the_assistant_fragment_names_every_setting_the_chat_changes():
    fragment = _unwrapped(ASSISTANT_FRAGMENT)

    assert (
        "You can change the name, the description, the instructions, the chat "
        "model and its settings, the knowledge and the ranking of its results, "
        "the knowledge mode, how files uploaded in a chat are handled, the MCP "
        "servers and their tools, the functions, the document template, how long "
        "conversations are kept and whether insights are on."
    ) in fragment
    assert "name only what changes; the rest stays" in fragment
    assert "sources on different ones cannot be combined" in fragment
    assert (
        "Everything else you cannot change, in either mode: attachments, skills, "
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


def test_publishing_and_unpublishing_always_ask_the_person_first():
    fragment = _unwrapped(ASSISTANT_FRAGMENT)

    assert "Publishing and unpublishing always ask the person first" in fragment
    assert (
        'Only when they ask for it, and only in "Redigera", call publish_assistant'
        in (fragment)
    )
    assert "nothing happens until they do" in fragment
    assert "do not repeat it unless they ask again" in fragment
    assert 'say that they switch to "Redigera" or publish under Publicering' in (
        fragment
    )


def test_earlier_versions_of_the_instructions_can_be_read():
    fragment = _unwrapped(ASSISTANT_FRAGMENT)

    assert "Earlier versions of the instructions are kept" in fragment
    assert "read_prompt_history reads them" in fragment
    assert "bringing one back is a change like any other" in fragment


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
