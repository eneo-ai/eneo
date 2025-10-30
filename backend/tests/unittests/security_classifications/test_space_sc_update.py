import uuid
from unittest.mock import MagicMock

import pytest

from intric.main.exceptions import BadRequestException
from intric.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from intric.spaces.space import Space


def test_update_space_with_high_sc():
    space = Space(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        user_id=None,
        tenant_space_id=uuid.uuid4(),
        name="Test Space",
        description="Test Description",
        embedding_models=[],
        completion_models=[],
        transcription_models=[],
        default_assistant=MagicMock(),
        assistants=[],
        apps=[],
        services=[],
        websites=[],
        collections=[],
        integration_knowledge_list=[],
        members={},
        group_chats=[],
        security_classification=None,
    )

    security_classification_low = SecurityClassification(
        name="low", tenant_id=MagicMock(), security_level=0, security_enabled=True
    )
    security_classification_high = SecurityClassification(
        name="high", tenant_id=MagicMock(), security_level=1, security_enabled=True
    )
    security_classification_god = SecurityClassification(
        name="god", tenant_id=MagicMock(), security_level=2, security_enabled=True
    )

    completion_model_low_1 = MagicMock(security_classification=security_classification_low)
    completion_model_low_2 = MagicMock(security_classification=security_classification_low)
    completion_model_high = MagicMock(security_classification=security_classification_high)
    completion_model_god = MagicMock(security_classification=security_classification_god)

    embedding_model_low = MagicMock(security_classification=security_classification_low)
    embedding_model_high = MagicMock(security_classification=security_classification_high)

    transcription_model_low = MagicMock(security_classification=security_classification_low)
    transcription_model_high = MagicMock(security_classification=security_classification_high)

    space.completion_models = [
        completion_model_low_1,
        completion_model_low_2,
        completion_model_high,
        completion_model_god,
    ]

    space.embedding_models = [
        embedding_model_low,
        embedding_model_high,
    ]

    space.transcription_models = [
        transcription_model_low,
        transcription_model_high,
    ]

    assert len(space.completion_models) == 4

    space.update(security_classification=None)

    assert len(space.completion_models) == 4
    assert completion_model_low_1 in space.completion_models
    assert completion_model_low_2 in space.completion_models
    assert completion_model_high in space.completion_models
    assert completion_model_god in space.completion_models
    assert len(space.embedding_models) == 2
    assert embedding_model_low in space.embedding_models
    assert embedding_model_high in space.embedding_models
    assert len(space.transcription_models) == 2
    assert transcription_model_low in space.transcription_models
    assert transcription_model_high in space.transcription_models

    space.update(security_classification=security_classification_low)

    assert len(space.completion_models) == 4
    assert completion_model_low_1 in space.completion_models
    assert completion_model_low_2 in space.completion_models
    assert completion_model_high in space.completion_models
    assert completion_model_god in space.completion_models
    assert len(space.embedding_models) == 2
    assert embedding_model_high in space.embedding_models
    assert embedding_model_low in space.embedding_models
    assert len(space.transcription_models) == 2
    assert transcription_model_low in space.transcription_models
    assert transcription_model_high in space.transcription_models

    space.update(security_classification=security_classification_high)

    assert len(space.completion_models) == 2
    assert completion_model_low_1 not in space.completion_models
    assert completion_model_low_2 not in space.completion_models
    assert completion_model_high in space.completion_models
    assert completion_model_god in space.completion_models
    assert len(space.embedding_models) == 1
    assert embedding_model_high in space.embedding_models
    assert embedding_model_low not in space.embedding_models
    assert len(space.transcription_models) == 1
    assert transcription_model_high in space.transcription_models
    assert transcription_model_low not in space.transcription_models

    space.update(security_classification=security_classification_god)

    assert len(space.completion_models) == 1
    assert completion_model_low_1 not in space.completion_models
    assert completion_model_low_2 not in space.completion_models
    assert completion_model_high not in space.completion_models
    assert completion_model_god in space.completion_models
    assert len(space.embedding_models) == 0
    assert len(space.transcription_models) == 0


def test_update_personal_space_with_sc():
    space = Space(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        tenant_space_id=uuid.uuid4(),
        name="Test Space",
        description="Test Description",
        embedding_models=[],
        completion_models=[],
        transcription_models=[],
        default_assistant=MagicMock(),
        assistants=[],
        apps=[],
        services=[],
        websites=[],
        collections=[],
        integration_knowledge_list=[],
        members={},
        group_chats=[],
        security_classification=None,
    )

    security_classification = SecurityClassification(
        name="low", tenant_id=MagicMock(), security_level=0, security_enabled=True
    )

    # Should raise BadRequestException
    with pytest.raises(BadRequestException):
        space.update(security_classification=security_classification)


def test_adding_models_with_lower_sc_than_space():
    space = Space(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        user_id=None,
        tenant_space_id= uuid.uuid4(),
        name="Test Space",
        description="Test Description",
        embedding_models=[],
        completion_models=[],
        transcription_models=[],
        default_assistant=MagicMock(),
        assistants=[],
        apps=[],
        services=[],
        websites=[],
        collections=[],
        integration_knowledge_list=[],
        members={},
        group_chats=[],
        security_classification=None,
    )

    completion_model_low = MagicMock(
        security_classification=SecurityClassification(
            name="low", tenant_id=MagicMock(), security_level=0, security_enabled=True
        )
    )
    completion_model_high = MagicMock(
        security_classification=SecurityClassification(
            name="high", tenant_id=MagicMock(), security_level=1, security_enabled=True
        )
    )

    space.update(completion_models=[completion_model_high])

    assert len(space.completion_models) == 1
    assert completion_model_high in space.completion_models

    security_classification = SecurityClassification(
        name="high", tenant_id=MagicMock(), security_level=1, security_enabled=True
    )

    with pytest.raises(BadRequestException):
        space.update(
            completion_models=[completion_model_low],
            security_classification=security_classification,
        )
    with pytest.raises(BadRequestException):
        space.update(completion_models=[completion_model_low])
    assert len(space.completion_models) == 1

    security_classification_happy_easter = SecurityClassification(
        name="happy easter", tenant_id=MagicMock(), security_level=2, security_enabled=True
    )
    space.update(security_classification=security_classification_happy_easter)

    assert len(space.completion_models) == 0
