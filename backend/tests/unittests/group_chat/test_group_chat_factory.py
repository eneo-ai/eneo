from types import SimpleNamespace
from uuid import uuid4

from intric.group_chat.domain.factories.group_chat_factory import GroupChatFactory


def _mapping(assistant_id, user_description="desc"):
    return SimpleNamespace(
        assistant_id=assistant_id,
        user_description=user_description,
    )


def _group_chat_db(group_chat_assistants):
    return SimpleNamespace(
        group_chat_assistants=group_chat_assistants,
        metadata_json=None,
        created_at=None,
        updated_at=None,
        id=uuid4(),
        user_id=uuid4(),
        space_id=uuid4(),
        name="Group chat",
        allow_mentions=True,
        show_response_label=True,
        published=False,
        insight_enabled=False,
        icon_id=None,
    )


def test_create_group_chat_from_db_skips_missing_member_assistant():
    """A member assistant dropped during space load (e.g. corrupt JSONB skipped
    by the validation belt) must not crash the whole space with StopIteration —
    the group chat degrades to its loadable members."""
    present_id = uuid4()
    missing_id = uuid4()
    present_assistant = SimpleNamespace(id=present_id)

    group_chat_db = _group_chat_db(
        [_mapping(present_id), _mapping(missing_id)]
    )

    group_chat = GroupChatFactory.create_group_chat_from_db(
        group_chat_db=group_chat_db,
        assistants=[present_assistant],
    )

    assert len(group_chat.assistants) == 1
    assert group_chat.assistants[0].assistant is present_assistant


def test_create_group_chat_from_db_keeps_all_present_members():
    a_id, b_id = uuid4(), uuid4()
    a, b = SimpleNamespace(id=a_id), SimpleNamespace(id=b_id)

    group_chat_db = _group_chat_db([_mapping(a_id), _mapping(b_id)])

    group_chat = GroupChatFactory.create_group_chat_from_db(
        group_chat_db=group_chat_db,
        assistants=[a, b],
    )

    assert [gca.assistant for gca in group_chat.assistants] == [a, b]
