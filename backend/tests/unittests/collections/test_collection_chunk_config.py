"""Partial chunk updates must be validated against what the collection already has.

Setting one field at a time was how a collection came to report 100/40 while its
chunks were split at 100/25: the size was accepted on its own, the retained overlap
was never re-examined, and the splitter reduced it much later during ingestion.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.collections.domain.collection import Collection
from eneo.main.exceptions import BadRequestException


def _collection(chunk_size: int | None, chunk_overlap: int | None) -> Collection:
    return Collection(
        id=uuid4(),
        created_at=None,
        updated_at=None,
        space_id=uuid4(),
        user_id=uuid4(),
        tenant_id=uuid4(),
        name="knowledge",
        size=0,
        num_info_blobs=0,
        embedding_model=SimpleNamespace(max_input=None),
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


def test_lowering_only_the_size_is_refused_when_the_retained_overlap_no_longer_fits():
    collection = _collection(chunk_size=200, chunk_overlap=40)

    with pytest.raises(BadRequestException, match="chunk_overlap must not exceed"):
        collection.update(chunk_size=100)

    # The rejected update must leave the collection exactly as it was.
    assert (collection.chunk_size, collection.chunk_overlap) == (200, 40)


def test_lowering_the_size_together_with_a_fitting_overlap_is_accepted():
    collection = _collection(chunk_size=200, chunk_overlap=40)

    collection.update(chunk_size=100, chunk_overlap=25)

    assert (collection.chunk_size, collection.chunk_overlap) == (100, 25)


def test_raising_only_the_size_keeps_the_retained_overlap():
    collection = _collection(chunk_size=200, chunk_overlap=40)

    collection.update(chunk_size=1000)

    assert (collection.chunk_size, collection.chunk_overlap) == (1000, 40)


def test_clearing_the_size_judges_the_overlap_against_the_platform_default():
    collection = _collection(chunk_size=1000, chunk_overlap=200)

    # 200 fits 1000 but not the platform default of 200, which is what the source
    # would split at once its own size is gone.
    with pytest.raises(BadRequestException, match="chunk_overlap must not exceed"):
        collection.update(chunk_size=None)

    assert (collection.chunk_size, collection.chunk_overlap) == (1000, 200)


def test_a_size_below_the_floor_is_refused():
    collection = _collection(chunk_size=None, chunk_overlap=None)

    with pytest.raises(BadRequestException, match="chunk_size must be at least"):
        collection.update(chunk_size=1)


def test_untouched_chunk_fields_are_left_alone():
    collection = _collection(chunk_size=200, chunk_overlap=40)

    collection.update(name="renamed")

    assert collection.name == "renamed"
    assert (collection.chunk_size, collection.chunk_overlap) == (200, 40)
