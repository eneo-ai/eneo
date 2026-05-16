"""Defensive coercion at the Scrapy `headers_received` signal boundary.

Scrapy's `headers_received(body_length=...)` signal docstring promises an
`int`, but in practice forwards the raw `Content-Length` header value,
which arrives as `str` (`"1024"`), `bytes` (`b"1024"`), `int`, or is
absent entirely (HTTP/1.1 chunked, HTTP/2 trailers). A previous version
of `FileSizeLimitStatsExtension.headers_received` annotated
`body_length: int` and called `_should_stop_file_download` directly,
producing the live worker crash:

    TypeError: '>' not supported between instances of 'str' and 'int'

This test pins the coercion helper that fixes the boundary so a
regression that re-introduces the bare comparison crashes here first.
"""

from __future__ import annotations

from intric.crawler.pipelines import _coerce_optional_nonnegative_int


def test_coerces_int_passthrough() -> None:
    assert _coerce_optional_nonnegative_int(1024) == 1024
    assert _coerce_optional_nonnegative_int(0) == 0


def test_rejects_negative_int() -> None:
    assert _coerce_optional_nonnegative_int(-1) is None


def test_rejects_bool_even_though_it_is_int_subclass() -> None:
    # `True` is `1` in Python but a Scrapy signal forwarding a `bool` to a
    # size argument is an upstream bug we should not silently coerce.
    assert _coerce_optional_nonnegative_int(True) is None
    assert _coerce_optional_nonnegative_int(False) is None


def test_coerces_str_decimal_to_int() -> None:
    assert _coerce_optional_nonnegative_int("1024") == 1024
    assert _coerce_optional_nonnegative_int(" 1024 ") == 1024
    assert _coerce_optional_nonnegative_int("0") == 0


def test_rejects_str_non_decimal() -> None:
    assert _coerce_optional_nonnegative_int("not-a-number") is None
    assert _coerce_optional_nonnegative_int("") is None
    assert _coerce_optional_nonnegative_int("   ") is None
    assert _coerce_optional_nonnegative_int("1.5") is None
    assert _coerce_optional_nonnegative_int("-1") is None


def test_coerces_bytes_decimal_to_int() -> None:
    assert _coerce_optional_nonnegative_int(b"1024") == 1024
    assert _coerce_optional_nonnegative_int(bytearray(b"512")) == 512


def test_rejects_bytes_non_ascii() -> None:
    assert _coerce_optional_nonnegative_int(b"\xff\xff") is None


def test_rejects_unhandled_types() -> None:
    assert _coerce_optional_nonnegative_int(None) is None
    assert _coerce_optional_nonnegative_int(3.14) is None
    assert _coerce_optional_nonnegative_int([]) is None
    assert _coerce_optional_nonnegative_int(object()) is None
