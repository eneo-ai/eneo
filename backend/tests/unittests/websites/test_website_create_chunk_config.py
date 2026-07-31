"""Website.create must honour chunk settings on both of its declared call styles.

The positional overload lists chunk_size and chunk_overlap after the auth pair, but the
positional branch used to read them from kwargs — so a type-checked positional caller
got a website silently built on platform defaults.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.main.exceptions import BadRequestException
from eneo.websites.domain.crawl_run import CrawlType
from eneo.websites.domain.website import UpdateInterval, Website


def _args() -> tuple[object, ...]:
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    return (
        uuid4(),  # space_id
        user,
        "https://example.se",
        "Example",  # name
        False,  # download_files
        CrawlType.CRAWL,
        UpdateInterval.NEVER,
        SimpleNamespace(id=uuid4(), max_input=None),  # embedding_model
    )


def test_positional_chunk_settings_reach_the_entity():
    website = Website.create(*_args(), None, None, 1000, 200)

    assert (website.chunk_size, website.chunk_overlap) == (1000, 200)


def test_positional_call_without_chunk_settings_uses_platform_defaults():
    website = Website.create(*_args(), None, None)

    assert (website.chunk_size, website.chunk_overlap) == (None, None)


def test_positional_chunk_settings_are_validated_like_keyword_ones():
    # The same owner must judge both call styles, or one of them becomes a way past
    # the policy.
    with pytest.raises(BadRequestException, match="chunk_overlap must not exceed"):
        Website.create(*_args(), None, None, 100, 40)

    with pytest.raises(BadRequestException, match="chunk_size must be at least"):
        Website.create(*_args(), None, None, 1, None)


def test_keyword_chunk_settings_still_reach_the_entity():
    space_id, user, url, name, download_files, crawl_type, interval, model = _args()

    website = Website.create(
        space_id=space_id,
        user=user,
        url=url,
        name=name,
        download_files=download_files,
        crawl_type=crawl_type,
        update_interval=interval,
        embedding_model=model,
        chunk_size=1000,
        chunk_overlap=200,
    )

    assert (website.chunk_size, website.chunk_overlap) == (1000, 200)
