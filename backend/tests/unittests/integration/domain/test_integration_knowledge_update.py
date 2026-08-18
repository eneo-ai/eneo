"""The partial-update contract for integration knowledge.

Chunking is editable on an integration source for the same reason it is on
collections and websites. The endpoint is shared with renaming, which makes the
sentinel load-bearing: an omitted chunk field must mean "leave it alone", because
resetting it would look like drift on the next sync and answer with a full re-index
of the whole corpus.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.embedding_models.domain import chunking
from eneo.embedding_models.domain.chunking import ChunkSettings
from eneo.integration.domain.entities.integration_knowledge import IntegrationKnowledge
from eneo.main.exceptions import BadRequestException


@pytest.fixture
def platform_defaults(monkeypatch: pytest.MonkeyPatch) -> ChunkSettings:
    settings = ChunkSettings(chunk_size=200, chunk_overlap=40)
    monkeypatch.setattr(chunking, "settings", settings)
    return settings


def _knowledge(*, chunk_size=None, chunk_overlap=None, max_input=8191):
    return IntegrationKnowledge(
        id=uuid4(),
        name="Original name",
        user_integration=SimpleNamespace(),
        space_id=uuid4(),
        tenant_id=uuid4(),
        embedding_model=SimpleNamespace(id=uuid4(), max_input=max_input),
        size=0,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


def test_a_rename_leaves_the_chunk_configuration_alone(platform_defaults):
    """The most dangerous regression this contract prevents.

    A rename that carried chunk_size=None would return the source to platform
    defaults. The next sync would see stamps that no longer match and re-embed
    every document — a full re-index triggered by editing a label.
    """
    knowledge = _knowledge(chunk_size=400, chunk_overlap=80)

    knowledge.update(name="New name")

    assert knowledge.name == "New name"
    assert (knowledge.chunk_size, knowledge.chunk_overlap) == (400, 80)


def test_a_chunking_change_leaves_the_name_alone(platform_defaults):
    knowledge = _knowledge(chunk_size=400, chunk_overlap=80)

    knowledge.update(chunk_size=600, chunk_overlap=100)

    assert knowledge.name == "Original name"
    assert (knowledge.chunk_size, knowledge.chunk_overlap) == (600, 100)


def test_a_size_only_change_keeps_the_stored_overlap(platform_defaults):
    """The two fields are one setting, so the merge happens against what is stored."""
    knowledge = _knowledge(chunk_size=400, chunk_overlap=80)

    knowledge.update(chunk_size=800)

    assert (knowledge.chunk_size, knowledge.chunk_overlap) == (800, 80)


def test_explicit_nulls_return_the_source_to_the_platform_default(platform_defaults):
    knowledge = _knowledge(chunk_size=400, chunk_overlap=80)

    knowledge.update(chunk_size=None, chunk_overlap=None)

    assert (knowledge.chunk_size, knowledge.chunk_overlap) == (None, None)


def test_customizing_one_side_stores_the_whole_pair(platform_defaults):
    """Pair-level customization, the same contract the API documents."""
    knowledge = _knowledge()

    knowledge.update(chunk_size=400)

    assert (knowledge.chunk_size, knowledge.chunk_overlap) == (
        400,
        platform_defaults.chunk_overlap,
    )


def test_the_model_ceiling_applies_to_an_update(platform_defaults):
    """A change is validated like a create: floor(300 * 0.6) = 180."""
    knowledge = _knowledge(max_input=300)

    knowledge.update(chunk_size=500, chunk_overlap=40)

    assert knowledge.chunk_size == 180


def test_an_impossible_pair_is_refused_rather_than_stored(platform_defaults):
    knowledge = _knowledge()

    with pytest.raises(BadRequestException, match="chunk_overlap must not exceed"):
        knowledge.update(chunk_size=200, chunk_overlap=150)

    # And the source is left exactly as it was.
    assert (knowledge.chunk_size, knowledge.chunk_overlap) == (None, None)
