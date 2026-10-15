"""A space's reader model choice: one of its own models or none, never a
model outside the space or below its classification, and dropped when the
model leaves the space."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.main.exceptions import BadRequestException
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from eneo.spaces.space import Space


def _classification(level: int) -> SecurityClassification:
    return SecurityClassification(
        id=uuid4(),
        tenant_id=uuid4(),
        name=f"klass {level}",
        security_level=level,
        security_enabled=True,
    )


def _model(level: int | None = None):
    return SimpleNamespace(
        id=uuid4(),
        can_access=True,
        supports_tool_calling=True,
        security_classification=_classification(level) if level is not None else None,
    )


def _space(models, *, classification=None, personal=False):
    return Space(
        id=uuid4(),
        tenant_id=uuid4(),
        tenant_space_id=None,
        user_id=uuid4() if personal else None,
        name="Shared",
        description=None,
        embedding_models=[],
        completion_models=list(models),
        transcription_models=[],
        mcp_servers=[],
        default_assistant=None,
        assistants=[],
        apps=[],
        services=[],
        websites=[],
        collections=[],
        integration_knowledge_list=[],
        members={},
        security_classification=classification,
    )


class TestReaderModelChoice:
    def test_defaults_to_inheriting_with_no_model(self):
        space = _space([_model()])

        assert (space.reader_model, space.reader_model_inherit) == (None, True)

    def test_choosing_one_of_the_spaces_models_stops_inheriting(self):
        turn, reader = _model(), _model()
        space = _space([turn, reader])

        space.update(reader_model=reader)

        assert (space.reader_model, space.reader_model_inherit) == (reader, False)

    def test_explicit_none_is_a_choice_of_its_own(self):
        space = _space([_model()])

        space.update(reader_model_inherit=False, reader_model=None)

        assert (space.reader_model, space.reader_model_inherit) == (None, False)

    def test_a_model_outside_the_space_is_refused(self):
        space = _space([_model()])

        with pytest.raises(BadRequestException):
            space.update(reader_model=_model())

    def test_a_model_below_the_space_classification_is_refused(self):
        low = _model(level=1)
        space = _space([low], classification=None)
        space.security_classification = _classification(2)

        with pytest.raises(BadRequestException):
            space.update(reader_model=low)

    def test_the_reader_is_dropped_when_its_model_leaves_the_space(self):
        turn, reader = _model(), _model()
        space = _space([turn, reader])
        space.update(reader_model=reader)

        space.update(completion_models=[turn])

        assert space.reader_model is None
        assert space.reader_model_inherit is False

    def test_personal_spaces_take_no_choice(self):
        space = _space([], personal=True)

        with pytest.raises(BadRequestException):
            space.update(reader_model_inherit=False)
