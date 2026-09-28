"""A destination refused by the resolver guard is skipped quietly (no retry,
no error traceback) and counted as a download failure; a genuine DNS failure
is left alone."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from scrapy.exceptions import IgnoreRequest
from twisted.internet.error import DNSLookupError

from eneo.crawler.destination_middleware import (
    REFUSED_STAT,
    DestinationRefusedMiddleware,
)
from eneo.crawler.destination_policy import DestinationPolicy, GuardedNameResolver


@pytest.fixture
def guard():
    guard = GuardedNameResolver(inner=MagicMock(), policy=DestinationPolicy())
    with patch("eneo.crawler.destination_middleware.reactor") as reactor:
        reactor.nameResolver = guard
        yield guard


def _request(url: str):
    return SimpleNamespace(url=url)


def test_refused_destination_becomes_a_counted_skip(guard):
    guard.note_refusal("localhost", ["127.0.0.1"])
    stats = MagicMock()
    mw = DestinationRefusedMiddleware(stats)

    with pytest.raises(IgnoreRequest):
        mw.process_exception(
            _request("http://localhost:8123/x"), DNSLookupError("no results"), None
        )
    stats.inc_value.assert_called_once_with(REFUSED_STAT, spider=None)


def test_genuine_dns_failure_is_left_to_scrapy(guard):
    stats = MagicMock()
    mw = DestinationRefusedMiddleware(stats)

    assert (
        mw.process_exception(
            _request("http://nx.example/"), DNSLookupError("no results"), None
        )
        is None
    )
    stats.inc_value.assert_not_called()


def test_other_exceptions_are_left_alone(guard):
    guard.note_refusal("localhost", ["127.0.0.1"])
    mw = DestinationRefusedMiddleware(MagicMock())
    assert (
        mw.process_exception(_request("http://localhost/"), TimeoutError(), None)
        is None
    )


def test_guard_remembers_a_bounded_number_of_refusals():
    guard = GuardedNameResolver(inner=MagicMock(), policy=DestinationPolicy())
    for i in range(1100):
        guard.note_refusal(f"h{i}.example", ["127.0.0.1"])
    assert guard.refused_addresses("h0.example") is None
    assert guard.refused_addresses("h1099.example") == ["127.0.0.1"]
    assert len(guard.refused) <= 1024
