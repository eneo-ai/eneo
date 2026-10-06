"""RFC 7643 §4.3 Enterprise User extension: validation and PATCH semantics.

Stored on ``users.scim_extensions`` as ``{SCIM_ENTERPRISE_USER_URN: {...}}``.
The inner object only ever holds canonical attribute names, string values for
the singular attributes, and ``manager`` as ``{"value"?, "$ref"?}``, so readers
have exactly one representation of "absent": a missing key.

``manager.displayName`` is readOnly (RFC 7643 §4.3) and is dropped on ingest;
RFC 7644 §3.5.2 directs a server to ignore client-supplied readOnly values.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from eneo.scim.constants import (
    SCIM_ENTERPRISE_USER_URN,
    SCIM_EXTENSION_MAX_ATTRIBUTES,
    SCIM_EXTENSION_MAX_BYTES,
    SCIM_EXTENSION_MAX_VALUE_CHARS,
)
from eneo.scim.domain.errors import ScimHttpError, ScimValidationError
from eneo.scim.schemas.user import PatchOperation

EnterpriseUser = dict[str, Any]

STRING_ATTRIBUTES = (
    "employeeNumber",
    "costCenter",
    "organization",
    "division",
    "department",
)
MANAGER = "manager"
_CANONICAL_ATTRIBUTES = {
    name.casefold(): name for name in (*STRING_ATTRIBUTES, MANAGER)
}
_MANAGER_SUB_ATTRIBUTES = {"value": "value", "$ref": "$ref"}
_MANAGER_READ_ONLY = {"displayname"}

_URN_FOLDED = SCIM_ENTERPRISE_USER_URN.casefold()


def is_enterprise_urn(key: str) -> bool:
    return key.casefold() == _URN_FOLDED


def split_request_extensions(
    extra: Mapping[str, Any] | None,
) -> tuple[bool, Any, list[str]]:
    """Separate the enterprise object from the other extra request keys.

    Returns ``(present, raw_enterprise, ignored_keys)``. ``ignored_keys`` names
    every other extra key (unknown extension URNs and stray non-URN keys) so the
    caller can log what the IdP sent — names only, never values.
    """
    present = False
    raw: Any = None
    ignored: list[str] = []
    for key, value in (extra or {}).items():
        if is_enterprise_urn(key):
            if present:
                raise ScimValidationError(
                    f"'{SCIM_ENTERPRISE_USER_URN}' was supplied more than once"
                )
            present, raw = True, value
        else:
            ignored.append(key)
    return present, raw, ignored


def parse_enterprise_object(raw: Any) -> EnterpriseUser:
    """Validate a whole Enterprise User object (POST, PUT, whole-URN PATCH).

    Unknown attributes are dropped, ``null`` means absent, and names are matched
    case-insensitively (RFC 7643 §2.1) and stored in canonical casing.
    """
    parsed: EnterpriseUser = {}
    _merge_object(parsed, raw)
    return parsed


def enterprise_from_column(column: Mapping[str, Any] | None) -> EnterpriseUser:
    stored = (column or {}).get(SCIM_ENTERPRISE_USER_URN)
    return dict(cast(dict[str, Any], stored)) if isinstance(stored, dict) else {}


def enterprise_to_column(enterprise: EnterpriseUser) -> dict[str, Any] | None:
    return {SCIM_ENTERPRISE_USER_URN: enterprise} if enterprise else None


@dataclass(frozen=True)
class _Target:
    """A PATCH path inside the enterprise extension.

    ``attribute`` None means the whole extension object; ``sub_attribute`` is
    only ever set for ``manager``.
    """

    attribute: str | None
    sub_attribute: str | None = None


def _parse_path(path: str) -> _Target | None:
    """Resolve a PATCH path against the enterprise URN.

    Returns None when the path is not in the enterprise extension (core
    attributes, other URNs). A path that *is* in the extension but names no
    known attribute is an error: once /Schemas advertises the extension, a
    silent no-op would tell the IdP a write succeeded when nothing changed.
    """
    if path[: len(SCIM_ENTERPRISE_USER_URN)].casefold() != _URN_FOLDED:
        return None
    rest = path[len(SCIM_ENTERPRISE_USER_URN) :]
    if rest == "":
        return _Target(attribute=None)
    if not rest.startswith(":"):
        return None  # a different URN that merely shares this prefix

    attribute_path = rest[1:]
    name, _, sub = attribute_path.partition(".")
    canonical = _CANONICAL_ATTRIBUTES.get(name.casefold())
    if canonical is None or "[" in attribute_path:
        raise _invalid_path(path)
    if not sub:
        return _Target(attribute=canonical)
    sub_canonical = _MANAGER_SUB_ATTRIBUTES.get(sub.casefold())
    if canonical != MANAGER or sub_canonical is None:
        raise _invalid_path(path)
    return _Target(attribute=MANAGER, sub_attribute=sub_canonical)


def apply_patch_operations(
    current: EnterpriseUser, operations: Iterable[PatchOperation]
) -> EnterpriseUser:
    """Fold the enterprise-extension parts of a PATCH request over ``current``.

    Pure: ``current`` is not mutated and nothing is written. Every operation is
    validated here, so a caller that runs this before touching the user row
    gets RFC 7644 §3.5.2 atomicity — one invalid operation rejects the whole
    request with the resource unchanged. Operations (or path-less value keys)
    outside the extension are ignored; the core-attribute handler owns them.
    """
    result: EnterpriseUser = dict(current)
    for operation in operations:
        op = operation.op.casefold()
        if op not in {"add", "replace", "remove"}:
            continue
        value: Any = operation.value
        if operation.path is None:
            if op != "remove" and isinstance(value, dict):
                _apply_pathless(result, cast(dict[str, Any], value))
            continue
        target = _parse_path(operation.path)
        if target is None:
            continue
        if op == "remove":
            _remove(result, target)
        else:
            _set(result, target, value)
    return result


def _apply_pathless(result: EnterpriseUser, value: dict[str, Any]) -> None:
    """Path-less add/replace: the value object may name the whole extension
    (``{URN: {...}}``) or individual attributes by fully qualified name
    (``{"URN:department": "..."}``); both forms are seen from IdPs."""
    for key, item in value.items():
        if is_enterprise_urn(key):
            _set(result, _Target(attribute=None), item)
            continue
        target = _parse_path(key)
        if target is not None:
            _set(result, target, item)


def _merge_object(result: EnterpriseUser, value: Any) -> None:
    """Set the attributes named in ``value``; leave the others unchanged.

    This is RFC 7644 §3.5.2.1/§3.5.2.3 for a complex target, ``manager``
    included, and — applied to an empty ``result`` — whole-object parsing.
    A null attribute removes it.
    """
    if value is None:
        return
    if not isinstance(value, dict):
        raise ScimValidationError(f"'{SCIM_ENTERPRISE_USER_URN}' must be an object")
    incoming = cast(dict[str, Any], value)
    _check_object_bounds(incoming)
    seen: set[str] = set()
    for key, item in incoming.items():
        canonical = _CANONICAL_ATTRIBUTES.get(key.casefold())
        if canonical is None:
            continue
        if canonical in seen:
            raise ScimValidationError(
                f"Enterprise attribute '{canonical}' was supplied more than once"
            )
        seen.add(canonical)
        _set_attribute(result, canonical, item)


def _set(result: EnterpriseUser, target: _Target, value: Any) -> None:
    if target.attribute is None:
        _merge_object(result, value)
    elif target.sub_attribute is None:
        _set_attribute(result, target.attribute, value)
    else:
        _set_attribute(result, MANAGER, {target.sub_attribute: value})


def _remove(result: EnterpriseUser, target: _Target) -> None:
    if target.attribute is None:
        result.clear()
    elif target.sub_attribute is None:
        result.pop(target.attribute, None)
    else:
        _set(result, target, None)


def _store(result: EnterpriseUser, attribute: str, value: Any) -> None:
    if value is None:
        result.pop(attribute, None)
    else:
        result[attribute] = value


def _set_attribute(result: EnterpriseUser, attribute: str, value: Any) -> None:
    if attribute == MANAGER:
        _store(result, MANAGER, _merge_manager(result.get(MANAGER), value))
    else:
        _store(result, attribute, _normalise_string(attribute, value))


def _normalise_string(attribute: str, value: Any) -> str | None:
    """A singular string attribute. ``null`` and ``""`` both mean unassigned
    (RFC 7643 §2.5); anything that is not a string is rejected, not coerced."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ScimValidationError(
            f"Enterprise attribute '{attribute}' must be a string"
        )
    if len(value) > SCIM_EXTENSION_MAX_VALUE_CHARS:
        raise ScimValidationError(
            f"Enterprise attribute '{attribute}' exceeds "
            f"{SCIM_EXTENSION_MAX_VALUE_CHARS} characters"
        )
    return value


def _merge_manager(current: Any, value: Any) -> dict[str, str] | None:
    """``manager`` is complex: an object sets only the sub-attributes it names
    and leaves the others unchanged (RFC 7644 §3.5.2.3), so a readOnly or
    unknown key never clears a stored reference. POST and PUT parse into an
    empty result, where this is a whole replacement."""
    if value is None:
        return None
    if isinstance(value, str):
        # IdPs are known to send the manager reference as a bare id string in
        # PATCH (`path: "...:manager", value: "<id>"`). Rejecting it would fail
        # the whole atomic request and stall the sync, so treat it as `value`.
        # It names a whole new reference, so a stored `$ref` is not kept.
        reference = _normalise_string("manager.value", value)
        return {"value": reference} if reference is not None else None
    if not isinstance(value, dict):
        raise ScimValidationError(
            "Enterprise attribute 'manager' must be an object with 'value' and/or '$ref'"
        )
    manager = dict(cast(dict[str, str], current or {}))
    for key, item in cast(dict[str, Any], value).items():
        folded = key.casefold()
        if folded in _MANAGER_READ_ONLY:
            continue
        sub = _MANAGER_SUB_ATTRIBUTES.get(folded)
        if sub is None:
            continue
        normalised = _normalise_string(f"manager.{sub}", item)
        if normalised is None:
            manager.pop(sub, None)
        else:
            manager[sub] = normalised
    return manager or None


def _check_object_bounds(attributes: dict[str, Any]) -> None:
    if len(attributes) > SCIM_EXTENSION_MAX_ATTRIBUTES:
        raise ScimValidationError(
            f"'{SCIM_ENTERPRISE_USER_URN}' has more than "
            f"{SCIM_EXTENSION_MAX_ATTRIBUTES} attributes"
        )
    try:
        size = len(json.dumps(attributes, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ScimValidationError(
            f"'{SCIM_ENTERPRISE_USER_URN}' is not valid JSON"
        ) from exc
    if size > SCIM_EXTENSION_MAX_BYTES:
        raise ScimValidationError(
            f"'{SCIM_ENTERPRISE_USER_URN}' exceeds {SCIM_EXTENSION_MAX_BYTES} bytes"
        )


def _invalid_path(path: str) -> ScimHttpError:
    return ScimHttpError(
        400,
        f"PATCH path '{path}' does not name an attribute of '{SCIM_ENTERPRISE_USER_URN}'",
        scim_type="invalidPath",
    )
