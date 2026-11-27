"""An assistant brings its model into the space, so the model has to meet the
space's level."""

import uuid
from unittest.mock import MagicMock

import pytest

from eneo.main.exceptions import BadRequestException
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from eneo.spaces.space import Space


def _level(level: int) -> SecurityClassification:
    return SecurityClassification(
        id=uuid.uuid4(),
        name=f"level {level}",
        tenant_id=uuid.uuid4(),
        security_level=level,
        security_enabled=True,
    )


def _space(security_classification=None) -> Space:
    return Space(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        user_id=None,
        tenant_space_id=uuid.uuid4(),
        name="Test Space",
        description=None,
        embedding_models=[],
        completion_models=[],
        transcription_models=[],
        mcp_servers=[],
        default_assistant=MagicMock(),
        assistants=[],
        apps=[],
        services=[],
        websites=[],
        collections=[],
        integration_knowledge_list=[],
        members={},
        group_chats=[],
        security_classification=security_classification,
    )


def _assistant_with_model(classification) -> tuple[MagicMock, MagicMock]:
    model = MagicMock(
        id=uuid.uuid4(), security_classification=classification, can_access=True
    )
    return MagicMock(id=uuid.uuid4(), completion_model=model), model


def test_an_assistant_whose_model_is_below_the_spaces_level_cannot_be_added():
    space = _space(_level(2))
    assistant, _ = _assistant_with_model(_level(1))

    with pytest.raises(BadRequestException):
        space.add_assistant(assistant)

    assert space.assistants == []
    assert space.completion_models == []


def test_an_assistant_whose_model_meets_the_spaces_level_is_added_with_it():
    space = _space(_level(2))
    assistant, model = _assistant_with_model(_level(2))

    space.add_assistant(assistant)

    assert space.assistants == [assistant]
    assert space.completion_models == [model]


def test_any_assistant_can_be_added_to_a_space_without_a_level():
    space = _space(None)
    assistant, _ = _assistant_with_model(None)

    space.add_assistant(assistant)

    assert space.assistants == [assistant]
