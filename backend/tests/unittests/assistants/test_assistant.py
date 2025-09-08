from unittest.mock import MagicMock

import pytest

from intric.ai_models.completion_models.completion_model import ModelKwargs
from intric.assistants.assistant import Assistant
from intric.main.exceptions import BadRequestException
from intric.main.models import NOT_PROVIDED


@pytest.fixture
def assistant():
    return Assistant(
        id=None,
        user=MagicMock(),
        name=MagicMock(),
        space_id=MagicMock(),
        prompt=None,
        completion_model=None,
        completion_model_kwargs=ModelKwargs(),
        logging_enabled=False,
        websites=[],
        collections=[],
        attachments=[],
        published=False,
    )


def test_assistant_has_embedding_model_id_none_if_no_groups_or_websites(
    assistant: Assistant,
):
    assert assistant.embedding_model_id is None


def test_can_not_add_websites_with_different_embedding_models(
    assistant: Assistant,
):
    website = MagicMock(embedding_model=MagicMock(id=1))
    website_2 = MagicMock(embedding_model=MagicMock(id=2))

    with pytest.raises(BadRequestException):
        assistant.update(websites=[website, website_2])


def test_can_not_add_groups_with_different_embedding_models(
    assistant: Assistant,
):
    group_1 = MagicMock(embedding_model=MagicMock(id=1))
    group_2 = MagicMock(embedding_model=MagicMock(id=2))

    with pytest.raises(BadRequestException):
        assistant.update(collections=[group_1, group_2])


def test_can_add_websites_with_same_embedding_model(assistant: Assistant):
    website_1 = MagicMock(embedding_model=MagicMock(id=1))
    website_2 = MagicMock(embedding_model=MagicMock(id=1))

    assistant.update(websites=[website_1, website_2])

    assert assistant.websites == [website_1, website_2]
    assert assistant.embedding_model_id == 1


def test_can_add_groups_with_same_embedding_model(assistant: Assistant):
    group_1 = MagicMock(embedding_model=MagicMock(id=1))
    group_2 = MagicMock(embedding_model=MagicMock(id=1))

    assistant.update(collections=[group_1, group_2])

    assert assistant.collections == [group_1, group_2]
    assert assistant.embedding_model_id == 1


def test_can_not_add_groups_and_websites_if_not_same_embedding_model(
    assistant: Assistant,
):
    websites = [MagicMock(embedding_model=MagicMock(id=1))]
    groups = [MagicMock(embedding_model=MagicMock(id=2))]

    with pytest.raises(BadRequestException):
        assistant.update(collections=groups, websites=websites)


def test_can_add_groups_and_websites_if_same_embedding_model(assistant: Assistant):
    websites = [MagicMock(embedding_model=MagicMock(id=1))]
    groups = [MagicMock(embedding_model=MagicMock(id=1))]

    assistant.update(collections=groups, websites=websites)

    assert assistant.collections == groups
    assert assistant.websites == websites


def test_can_not_add_groups_if_not_same_embedding_model_as_previous_websites(
    assistant: Assistant,
):
    assistant.websites = [MagicMock(embedding_model=MagicMock(id=1))]
    groups = [MagicMock(embedding_model=MagicMock(id=2))]

    with pytest.raises(BadRequestException):
        assistant.update(collections=groups)


def test_can_not_add_websites_if_not_same_embedding_model_as_previous_groups(
    assistant: Assistant,
):
    assistant.collections = [MagicMock(embedding_model=MagicMock(id=1))]
    websites = [MagicMock(embedding_model=MagicMock(id=2))]

    with pytest.raises(BadRequestException):
        assistant.update(websites=websites)


def test_can_override_previous_groups(assistant: Assistant):
    assistant.collections = [MagicMock(embedding_model=MagicMock(id=1))]
    new_groups = [MagicMock(embedding_model=MagicMock(id=2))]

    assistant.update(collections=new_groups)

    assert assistant.collections == new_groups


def test_can_override_previous_websites(assistant: Assistant):
    assistant.websites = [MagicMock(embedding_model=MagicMock(id=1))]
    new_websites = [MagicMock(embedding_model=MagicMock(id=2))]

    assistant.update(websites=new_websites)

    assert assistant.websites == new_websites


def test_can_override_previous_integration_knowledge_list(assistant: Assistant):
    assistant.integration_knowledge_list = [MagicMock(embedding_model=MagicMock(id=1))]
    new_list = [MagicMock(embedding_model=MagicMock(id=2))]

    assistant.update(integration_knowledge_list=new_list)

    assert assistant.integration_knowledge_list == new_list


def test_can_set_groups_to_empty_list(assistant: Assistant):
    assistant.collections = [MagicMock(embedding_model=MagicMock(id=1))]

    assistant.update(collections=[])

    assert assistant.collections == []


def test_can_set_websites_to_empty_list(assistant: Assistant):
    assistant.websites = [MagicMock(embedding_model=MagicMock(id=1))]

    assistant.update(websites=[])

    assert assistant.websites == []


def test_can_set_websites_to_empty_list_and_groups_to_new_embedding_model(
    assistant: Assistant,
):
    assistant.websites = [MagicMock(embedding_model=MagicMock(id=1))]
    groups = [MagicMock(embedding_model=MagicMock(id=2))]

    assistant.update(websites=[], collections=groups)

    assert assistant.websites == []
    assert assistant.collections == groups


def test_can_set_groups_to_empty_list_and_websites_to_new_embedding_model(
    assistant: Assistant,
):
    assistant.collections = [MagicMock(embedding_model=MagicMock(id=1))]
    websites = [MagicMock(embedding_model=MagicMock(id=2))]

    assistant.update(websites=websites, collections=[])

    assert assistant.websites == websites
    assert assistant.collections == []


def test_can_set_integration_knowledge_to_empty_list(assistant: Assistant):
    assistant.integration_knowledge_list = [MagicMock(embedding_model=MagicMock(id=1))]

    assistant.update(integration_knowledge_list=[])

    assert assistant.integration_knowledge_list == []


def test_has_knowledge(assistant: Assistant):
    embedding_model = MagicMock()

    # Test when both groups and websites are non-empty
    assistant.collections = [MagicMock(embedding_model=embedding_model)]
    assistant.websites = [MagicMock(embedding_model=embedding_model)]
    assert assistant.has_knowledge()

    # Test when only groups are non-empty
    assistant.collections = [MagicMock(embedding_model=embedding_model)]
    assistant.websites = []
    assert assistant.has_knowledge()

    # Test when only websites are non-empty
    assistant.collections = []
    assistant.websites = [MagicMock(embedding_model=embedding_model)]
    assert assistant.has_knowledge()

    # Test when both groups and websites are empty
    assistant.collections = []
    assistant.websites = []
    assert not assistant.has_knowledge()

    # Test when setting integration knowledge
    assistant.integration_knowledge_list = [MagicMock(embedding_model=MagicMock(id=1))]
    assert assistant.has_knowledge()


def test_update_metadata_json(assistant: Assistant):
    metadata_json = {"key": "value"}
    assistant.update(metadata_json=metadata_json)
    assert assistant.metadata_json == metadata_json

    assistant.update(metadata_json=NOT_PROVIDED)
    assert assistant.metadata_json == metadata_json

    assistant.update(metadata_json=None)
    assert assistant.metadata_json is None

    assistant.update(metadata_json=NOT_PROVIDED)
    assert assistant.metadata_json is None
