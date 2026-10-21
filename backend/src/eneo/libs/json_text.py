"""Keep tool records representable in PostgreSQL JSONB without altering inputs."""

from typing import Any, cast


def contains_null_character(value: Any) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(
            contains_null_character(k) or contains_null_character(v)
            for k, v in cast(dict[Any, Any], value).items()
        )
    if isinstance(value, (list, tuple)):
        return any(
            contains_null_character(item)
            for item in cast(list[Any] | tuple[Any, ...], value)
        )
    return False


def escape_null_characters(value: Any) -> Any:
    """Escape invalid text visibly, rather than silently joining words or digits.

    Applied only to records, never to executable tool arguments. PostgreSQL
    rejects NUL even inside JSON strings; a literal backslash-u0000 is safe.
    """
    if isinstance(value, str):
        return value.replace("\x00", "\\u0000")
    if isinstance(value, dict):
        return {
            escape_null_characters(k): escape_null_characters(v)
            for k, v in cast(dict[Any, Any], value).items()
        }
    if isinstance(value, (list, tuple)):
        return [
            escape_null_characters(item)
            for item in cast(list[Any] | tuple[Any, ...], value)
        ]
    return value
