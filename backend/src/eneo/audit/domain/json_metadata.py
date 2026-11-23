"""Audit metadata as the JSON it is stored as."""

from typing import Any, cast

from pydantic_core import to_jsonable_python


def json_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """`metadata` with every value one that JSON can hold.

    Callers describe a change with the values they have at hand: datetimes,
    UUIDs, enum members, models. A queued event is pickled, so those reach the
    insert unchanged, where the JSONB column's encoder rejects them and the
    event is lost.
    """
    return cast(
        dict[str, Any],
        to_jsonable_python(metadata, fallback=str, bytes_mode="base64"),
    )
