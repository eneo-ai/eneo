from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import cast

from pydantic import BaseModel

from eneo.json_types import JsonObject, JsonValue


def canonical_json_bytes(value: JsonValue) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def json_object_from_model(model: BaseModel) -> JsonObject:
    return _json_object(model.model_dump(mode="json"))


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def hash_json_value(value: JsonValue) -> str:
    return sha256_hex(canonical_json_bytes(value))


def compose_content_checksum(
    *,
    spec_hash: str,
    manifest_hash: str,
    requirements_hash: str,
    provenance_hash: str,
) -> str:
    checksum_input: JsonObject = {
        "manifest_hash": manifest_hash,
        "provenance_hash": provenance_hash,
        "requirements_hash": requirements_hash,
        "spec_hash": spec_hash,
    }
    return hash_json_value(checksum_input)


def _json_object(value: object) -> JsonObject:
    if not isinstance(value, Mapping):
        raise TypeError("Expected a JSON object.")
    mapping = cast(Mapping[object, object], value)
    result: JsonObject = {}
    for key, nested_value in mapping.items():
        if not isinstance(key, str):
            raise TypeError("JSON object keys must be strings.")
        result[key] = _json_value(nested_value)
    return result


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in cast(list[object], value)]
    if isinstance(value, Mapping):
        return _json_object(cast(Mapping[object, object], value))
    raise TypeError(f"Unsupported JSON value type: {type(value).__name__}.")
