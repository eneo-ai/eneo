"""Credential-free file identifiers at the model boundary.

Handles are identifiers, not authorization. Only the current request's trusted
file map can resolve them. MCP providers continue to receive their original URLs.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID

from eneo.authentication.signed_urls import (
    redact_reference_tokens,
    redact_reference_tokens_in_json,
)

HANDLE_PREFIX = "eneo-file:"
HANDLE_PATTERN = r"eneo-file:[0-9a-f]{32}"
_HANDLE = re.compile(HANDLE_PATTERN + r"$")
# Historical arguments/results can contain URLs inside JSON text or prose.
_LEGACY_LINK = re.compile(
    r"https?://[^\s\"'<>]+?/api/v1/files/(?P<id>[0-9a-fA-F-]{36})"
    r"/original/download[^\s\"'<>]*"
)


def file_handle(file_id: UUID) -> str:
    return HANDLE_PREFIX + file_id.hex


class UnknownFileReference(ValueError):
    """The model supplied a handle that this request cannot resolve."""


def resolve_file_handles(value: Any, current_urls: Mapping[UUID, str]) -> Any:
    """Resolve exact argument values only; never expand credentials into prose."""
    if isinstance(value, str):
        if not value.startswith(HANDLE_PREFIX):
            return value
        if not _HANDLE.fullmatch(value):
            raise UnknownFileReference("Invalid file reference")
        current = current_urls.get(UUID(hex=value[len(HANDLE_PREFIX) :]))
        if current is None:
            raise UnknownFileReference("File is not available in this conversation")
        return current
    if isinstance(value, dict):
        return {
            key: resolve_file_handles(item, current_urls)
            for key, item in cast(dict[str, Any], value).items()
        }
    if isinstance(value, list):
        return [
            resolve_file_handles(item, current_urls) for item in cast(list[Any], value)
        ]
    return value


def handle_file_ids(value: Any) -> set[UUID]:
    """Identities in exact handle values, for app-originating-call checks."""
    if isinstance(value, str):
        return (
            {UUID(hex=value[len(HANDLE_PREFIX) :])}
            if _HANDLE.fullmatch(value)
            else set()
        )
    if isinstance(value, dict):
        return set[UUID]().union(
            *(handle_file_ids(item) for item in cast(dict[str, Any], value).values())
        )
    if isinstance(value, list):
        return set[UUID]().union(
            *(handle_file_ids(item) for item in cast(list[Any], value))
        )
    return set()


def model_file_references(value: Any, current_urls: Mapping[UUID, str]) -> Any:
    """Replace current/legacy file URLs before model exposure, without mutating input.

    Unknown original links stay masked. Mapping a known historical file id to
    a handle grants no access: dispatch resolves against its own authorized map.
    """
    if isinstance(value, str):
        for file_id, url in current_urls.items():
            value = value.replace(url, file_handle(file_id))
            # Some providers serialize URLs with escaped slashes in JSON text.
            value = value.replace(url.replace("/", r"\/"), file_handle(file_id))

        def replace(match: re.Match[str]) -> str:
            try:
                file_id = UUID(match.group("id"))
            except ValueError:
                return match.group(0)
            return file_handle(file_id) if file_id in current_urls else match.group(0)

        value = _LEGACY_LINK.sub(replace, value)
        return redact_reference_tokens_in_json(
            cast(str, redact_reference_tokens(value))
        )
    if isinstance(value, dict):
        return {
            key: model_file_references(item, current_urls)
            for key, item in cast(dict[str, Any], value).items()
        }
    if isinstance(value, list):
        return [
            model_file_references(item, current_urls) for item in cast(list[Any], value)
        ]
    return value


FILE_HANDLE_INSTRUCTION = (
    "For Eneo conversation files, pass the file_ref value (eneo-file:...) unchanged "
    "in the tool's URL input. Eneo resolves it to an authorized URL before the "
    "provider runs. Never construct download URLs or tokens. Ordinary external "
    "web URLs still use the provider's normal inputs."
)


def model_file_schema(schema: Any, property_name: str = "") -> Any:
    """Offer handles in URL slots without changing the provider's stored schema."""
    if not isinstance(schema, dict):
        return schema
    result = dict(cast(dict[str, Any], schema))
    for key in ("anyOf", "oneOf", "allOf"):
        if isinstance(result.get(key), list):
            result[key] = [
                model_file_schema(item, property_name)
                for item in cast(list[Any], result[key])
            ]
    if isinstance(result.get("properties"), dict):
        result["properties"] = {
            name: model_file_schema(item, name)
            for name, item in cast(dict[str, Any], result["properties"]).items()
        }
    for key in ("$defs", "definitions"):
        if isinstance(result.get(key), dict):
            result[key] = {
                name: model_file_schema(item)
                for name, item in cast(dict[str, Any], result[key]).items()
            }
    if isinstance(result.get("items"), dict):
        result["items"] = model_file_schema(result["items"], property_name)
    is_url = (
        property_name.lower() in {"url", "urls", "uri", "uris", "href"}
        or property_name.lower().endswith(("_url", "_urls"))
        or result.get("format") in {"uri", "uri-reference", "url"}
    )
    if result.get("type") == "string" and is_url:
        return {
            "description": FILE_HANDLE_INSTRUCTION
            + " "
            + str(result.get("description", "")),
            "anyOf": [
                result,
                {"type": "string", "pattern": "^" + HANDLE_PATTERN + "$"},
            ],
        }
    return result
