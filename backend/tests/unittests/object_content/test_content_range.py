import pytest

from eneo.object_content.content import ByteRange, InvalidContentRangeError


@pytest.mark.parametrize(
    ("header", "size_bytes", "expected"),
    [
        ("bytes=2-5", 10, ByteRange(start=2, end=5, total=10)),
        ("bytes=7-", 10, ByteRange(start=7, end=9, total=10)),
        ("bytes=-3", 10, ByteRange(start=7, end=9, total=10)),
    ],
)
def test_byte_range_accepts_one_satisfiable_range(
    header: str, size_bytes: int, expected: ByteRange
) -> None:
    assert ByteRange.parse(header, size_bytes=size_bytes) == expected


@pytest.mark.parametrize(
    "header",
    [
        "items=0-1",
        "bytes=0-1,4-5",
        "bytes=10-11",
        "bytes=5-4",
        "bytes=-0",
    ],
)
def test_byte_range_rejects_invalid_or_unsatisfiable_ranges(header: str) -> None:
    with pytest.raises(InvalidContentRangeError):
        ByteRange.parse(header, size_bytes=10)
