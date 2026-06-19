"""Shared JSON type aliases; runtime validation belongs at API/persistence edges."""

from __future__ import annotations

from typing import TypeAlias

from pydantic import JsonValue

JsonScalar: TypeAlias = str | int | float | bool | None
JsonObject: TypeAlias = dict[str, JsonValue]

__all__ = ["JsonObject", "JsonScalar", "JsonValue"]
