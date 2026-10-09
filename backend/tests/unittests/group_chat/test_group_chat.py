from uuid import uuid4

from eneo.group_chat.domain.entities.group_chat import GroupChat, GroupChatAssistant


def _group_chat(assistants=None) -> GroupChat:
    return GroupChat(
        id=uuid4(),
        created_at=None,
        updated_at=None,
        user_id=uuid4(),
        space_id=uuid4(),
        name="Group chat",
        assistants=assistants or [],
        allow_mentions=False,
        show_response_label=False,
        published=False,
    )


def test_update_without_a_member_list_is_not_a_replacement():
    group_chat = _group_chat()

    group_chat.update(name="Renamed")

    assert group_chat.assistants_replaced is False


def test_update_with_a_member_list_marks_the_membership_as_replaced():
    """Also for an empty list: clear-all is an explicit replacement, which the
    repository must honour even for members the space loader skipped."""
    group_chat = _group_chat(assistants=[GroupChatAssistant(assistant=object())])  # type: ignore[arg-type]

    group_chat.update(new_assistants=[])

    assert group_chat.assistants == []
    assert group_chat.assistants_replaced is True
