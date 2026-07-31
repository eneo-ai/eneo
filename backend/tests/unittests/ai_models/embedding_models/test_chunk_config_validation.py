"""The request models must reject chunk values the splitter cannot honour.

RecursiveCharacterTextSplitter raises on chunk_size <= 0, and the raise happens deep
in ingestion — in the crawl worker, long after the request that stored the value has
returned 200. Rejecting at the edge keeps the failure where the caller can see it.
"""

import pytest
from pydantic import ValidationError

from eneo.collections.presentation.collection_models import CollectionUpdate
from eneo.spaces.api.space_models import (
    CreateSpaceGroupsRequest,
    CreateSpaceIntegrationKnowledge,
    CreateSpaceIntegrationKnowledgeBatchRequest,
)
from eneo.websites.presentation.website_models import WebsiteCreate, WebsiteUpdate

MODEL_ID = {"id": "00000000-0000-0000-0000-000000000001"}


def _build(model: type, **chunk_kwargs: object):
    """Instantiate a request model with only its required fields plus chunk config."""
    required: dict[str, object] = {
        CollectionUpdate: {"name": "c"},
        CreateSpaceGroupsRequest: {"name": "c"},
        CreateSpaceIntegrationKnowledge: {
            "name": "k",
            "url": "https://example.com",
            "embedding_model": MODEL_ID,
        },
        CreateSpaceIntegrationKnowledgeBatchRequest: {
            "embedding_model": MODEL_ID,
            "items": [{"name": "k", "url": "https://example.com"}],
        },
        WebsiteCreate: {"url": "https://example.com"},
        WebsiteUpdate: {},
    }[model]
    return model(**required, **chunk_kwargs)


REQUEST_MODELS = [
    CollectionUpdate,
    CreateSpaceGroupsRequest,
    CreateSpaceIntegrationKnowledge,
    CreateSpaceIntegrationKnowledgeBatchRequest,
    WebsiteCreate,
    WebsiteUpdate,
]


def _rejected_fields(excinfo: pytest.ExceptionInfo[ValidationError]) -> set[str]:
    """Which fields the error is actually about — so a missing required field in the
    test's own setup cannot make a negative test pass for the wrong reason."""
    return {str(error["loc"][0]) for error in excinfo.value.errors() if error["loc"]}


@pytest.mark.parametrize("model", REQUEST_MODELS, ids=lambda m: m.__name__)
@pytest.mark.parametrize("chunk_size", [0, -1, -200])
def test_chunk_size_below_one_is_rejected(model: type, chunk_size: int):
    with pytest.raises(ValidationError) as excinfo:
        _build(model, chunk_size=chunk_size)

    assert "chunk_size" in _rejected_fields(excinfo)


@pytest.mark.parametrize("model", REQUEST_MODELS, ids=lambda m: m.__name__)
def test_negative_chunk_overlap_is_rejected(model: type):
    with pytest.raises(ValidationError) as excinfo:
        _build(model, chunk_overlap=-1)

    assert "chunk_overlap" in _rejected_fields(excinfo)


@pytest.mark.parametrize("model", REQUEST_MODELS, ids=lambda m: m.__name__)
def test_valid_values_are_accepted(model: type):
    instance = _build(model, chunk_size=1000, chunk_overlap=100)

    assert instance.chunk_size == 1000
    assert instance.chunk_overlap == 100


@pytest.mark.parametrize("model", REQUEST_MODELS, ids=lambda m: m.__name__)
def test_overlap_above_the_platform_ceiling_is_rejected(model: type):
    # 40 of 50 is 80% overlap. Accepting it and indexing 10 instead would make the
    # stored and displayed setting disagree with the splitter.
    # The rule spans two fields, so pydantic reports it at model level rather than
    # against one field; assert on the message the caller actually sees.
    with pytest.raises(ValidationError, match="chunk_overlap must not exceed"):
        _build(model, chunk_size=50, chunk_overlap=40)


@pytest.mark.parametrize("model", REQUEST_MODELS, ids=lambda m: m.__name__)
def test_overlap_exactly_on_the_ceiling_is_accepted(model: type):
    instance = _build(model, chunk_size=50, chunk_overlap=10)

    assert (instance.chunk_size, instance.chunk_overlap) == (50, 10)


@pytest.mark.parametrize("model", REQUEST_MODELS, ids=lambda m: m.__name__)
def test_the_platform_default_pair_is_accepted(model: type):
    # The default 200/40 sits exactly on the ceiling; if this ever fails, the default
    # and the policy have drifted apart.
    instance = _build(model, chunk_size=200, chunk_overlap=40)

    assert (instance.chunk_size, instance.chunk_overlap) == (200, 40)


@pytest.mark.parametrize("model", REQUEST_MODELS, ids=lambda m: m.__name__)
def test_zero_overlap_is_accepted(model: type):
    # Zero overlap is meaningful: adjacent chunks simply do not overlap.
    assert _build(model, chunk_overlap=0).chunk_overlap == 0


@pytest.mark.parametrize("model", REQUEST_MODELS, ids=lambda m: m.__name__)
def test_null_still_means_use_the_platform_default(model: type):
    # The whole feature rests on null being distinguishable from a number, so the
    # bounds must not accidentally make null invalid.
    instance = _build(model, chunk_size=None, chunk_overlap=None)

    assert instance.chunk_size is None
    assert instance.chunk_overlap is None
