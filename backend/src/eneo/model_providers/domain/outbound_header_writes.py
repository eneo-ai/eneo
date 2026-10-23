"""Writing a provider's outbound header list, and auditing the change.

The list has replace semantics, keyed by a server-assigned ``id`` so that
renaming and replacing stay distinguishable:

- an entry with an ``id`` and no ``value`` keeps the stored value;
- an entry with an ``id`` and a ``value`` replaces it;
- an entry without an ``id`` is new and must supply ``value``;
- a stored header whose ``id`` is absent is deleted.

``fallback`` follows the same rule (``None`` clears it). A secret value is
never returned, so a client can only keep it by omitting it, and a submitted
value equal to the mask string is refused. Turning ``secret`` off requires the
value in the same request: an admin who cannot retype it is not in a position
to decide it is safe to expose. For the same reason, a secret kept by omission
is never moved to a new destination (``retained_secret_headers``). A kept
secret that no longer decrypts must be entered again or removed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from eneo.model_providers.domain.model_provider import MASKED_HEADER_VALUE
from eneo.model_providers.domain.outbound_headers import (
    Encoding,
    OnMissing,
    OutboundHeader,
    OutboundHeaderConfigError,
    header_classification,
    validate_headers,
)


class StoredSecretUnreadable(Exception):
    """Raised by a ``decrypt`` callable when a stored secret cannot be read,
    e.g. after ``ENCRYPTION_KEY`` changed."""


@dataclass(frozen=True)
class OutboundHeaderWrite:
    id: str | None
    name: str
    encoding: Encoding = "percent"
    secret: bool = False
    on_missing: OnMissing = "omit"
    value: str | None = field(default=None, repr=False)
    value_supplied: bool = False
    fallback: str | None = field(default=None, repr=False)
    fallback_supplied: bool = False


def apply_header_writes(
    stored: Sequence[Mapping[str, Any]],
    writes: Sequence[OutboundHeaderWrite],
    *,
    provider_type: str,
    encrypt: Callable[[str], str],
    decrypt: Callable[[str], str],
) -> list[dict[str, Any]]:
    """Return the new stored list. Raises ``OutboundHeaderConfigError``.

    ``decrypt`` raises ``StoredSecretUnreadable`` for a secret it cannot read.
    """
    by_id = {str(entry["id"]): entry for entry in stored}
    seen_ids: set[str] = set()
    planned: list[tuple[OutboundHeader, Mapping[str, Any] | None]] = []

    for write in writes:
        existing: Mapping[str, Any] | None = None
        if write.id is not None:
            existing = by_id.get(write.id)
            if existing is None:
                raise OutboundHeaderConfigError(f"Unknown header id '{write.id}'")
            if write.id in seen_ids:
                raise OutboundHeaderConfigError(f"Header id '{write.id}' appears twice")
            seen_ids.add(write.id)

        was_secret = bool(existing and existing.get("secret"))
        value = _next_value(write, existing, was_secret, decrypt)
        fallback = _next_fallback(write, existing, was_secret, decrypt)
        planned.append(
            (
                OutboundHeader(
                    id=write.id or uuid4().hex,
                    name=write.name,
                    value=value,
                    encoding=write.encoding,
                    secret=write.secret,
                    on_missing=write.on_missing,
                    fallback=fallback,
                ),
                existing,
            )
        )

    validate_headers([header for header, _ in planned], provider_type)
    return [
        _to_stored(header, existing, write, encrypt)
        for (header, existing), write in zip(planned, writes)
    ]


def retained_secret_headers(
    stored: Sequence[Mapping[str, Any]],
    writes: Sequence[OutboundHeaderWrite] | None,
) -> list[str]:
    """Names of the secret headers whose stored value or fallback this write
    keeps without the client supplying it. ``writes`` None keeps the list."""
    if writes is None:
        return [str(entry["name"]) for entry in stored if entry.get("secret")]
    by_id = {str(entry["id"]): entry for entry in stored}
    names: list[str] = []
    for write in writes:
        existing = by_id.get(write.id) if write.id is not None else None
        if existing is None or not existing.get("secret"):
            continue
        keeps_fallback = bool(existing.get("fallback")) and not write.fallback_supplied
        if not write.value_supplied or keeps_fallback:
            names.append(write.name)
    return names


def _next_value(
    write: OutboundHeaderWrite,
    existing: Mapping[str, Any] | None,
    was_secret: bool,
    decrypt: Callable[[str], str],
) -> str:
    if write.value_supplied:
        if write.value == MASKED_HEADER_VALUE:
            raise OutboundHeaderConfigError(
                f"Header '{write.name}': enter the value, or omit it to keep the stored one"
            )
        if not write.value:
            raise OutboundHeaderConfigError(f"Header '{write.name}' needs a value")
        return write.value
    if existing is None:
        raise OutboundHeaderConfigError(f"New header '{write.name}' needs a value")
    if was_secret and not write.secret:
        raise OutboundHeaderConfigError(
            f"Header '{write.name}': re-enter the value to turn off 'secret'"
        )
    stored_value = str(existing["value"])
    if not was_secret:
        return stored_value
    return _read_stored_secret(write.name, "value", stored_value, decrypt)


def _next_fallback(
    write: OutboundHeaderWrite,
    existing: Mapping[str, Any] | None,
    was_secret: bool,
    decrypt: Callable[[str], str],
) -> str | None:
    if write.fallback_supplied:
        if write.fallback == MASKED_HEADER_VALUE:
            raise OutboundHeaderConfigError(
                f"Header '{write.name}': enter the fallback, or omit it to keep the stored one"
            )
        return write.fallback or None
    stored_fallback = existing.get("fallback") if existing is not None else None
    if not stored_fallback:
        return None
    if was_secret and not write.secret:
        raise OutboundHeaderConfigError(
            f"Header '{write.name}': re-enter the fallback to turn off 'secret'"
        )
    if not was_secret:
        return str(stored_fallback)
    return _read_stored_secret(write.name, "fallback", str(stored_fallback), decrypt)


def _read_stored_secret(
    name: str, part: str, ciphertext: str, decrypt: Callable[[str], str]
) -> str:
    try:
        return decrypt(ciphertext)
    except StoredSecretUnreadable:
        # The edit that repairs it is this one, so it is a 400, not a 500.
        raise OutboundHeaderConfigError(
            f"Header '{name}': the stored secret {part} cannot be read; "
            "enter it again or remove the header"
        ) from None


def _to_stored(
    header: OutboundHeader,
    existing: Mapping[str, Any] | None,
    write: OutboundHeaderWrite,
    encrypt: Callable[[str], str],
) -> dict[str, Any]:
    keep_ciphertext = (
        header.secret and existing is not None and bool(existing.get("secret"))
    )

    def protect(plaintext: str | None, supplied: bool, stored_key: str) -> str | None:
        if plaintext is None or not header.secret:
            return plaintext
        if keep_ciphertext and not supplied:
            # Unchanged secret: keep the stored ciphertext, so an edit that
            # does not touch the value does not look like a new one.
            return str(existing[stored_key]) if existing is not None else None
        return encrypt(plaintext)

    return {
        "id": header.id,
        "name": header.name,
        "value": protect(header.value, write.value_supplied, "value"),
        "encoding": header.encoding,
        "secret": header.secret,
        "on_missing": header.on_missing,
        "fallback": protect(header.fallback, write.fallback_supplied, "fallback"),
        "classification": header_classification(header.value),
    }


def _audit_view(entry: Mapping[str, Any], masked: bool) -> dict[str, Any]:
    fallback = entry.get("fallback")
    return {
        "name": entry["name"],
        "value": MASKED_HEADER_VALUE if masked else entry["value"],
        "encoding": entry.get("encoding", "percent"),
        "secret": bool(entry.get("secret")),
        "on_missing": entry.get("on_missing", "omit"),
        "fallback": None
        if fallback is None
        else MASKED_HEADER_VALUE
        if masked
        else fallback,
    }


def _plaintext_changed(
    old: Mapping[str, Any],
    new: Mapping[str, Any],
    key: str,
    decrypt: Callable[[str], str],
) -> bool:
    """Whether the value (or fallback) itself changed. A secret is stored
    encrypted, so only ticking *Secret* changes the stored form, not the value."""
    old_stored, new_stored = old.get(key), new.get(key)
    if old_stored == new_stored:
        return False
    if old_stored is None or new_stored is None:
        return True

    def plaintext(entry: Mapping[str, Any], stored: Any) -> str:
        return decrypt(str(stored)) if entry.get("secret") else str(stored)

    try:
        return plaintext(old, old_stored) != plaintext(new, new_stored)
    except StoredSecretUnreadable:
        # An unreadable old secret can only have been replaced.
        return True


def header_audit_changes(
    before: Sequence[Mapping[str, Any]],
    after: Sequence[Mapping[str, Any]],
    *,
    decrypt: Callable[[str], str],
) -> dict[str, Any] | None:
    """The change as an audit record: names, templates, encoding and policy in
    clear; value and fallback masked wherever ``secret`` is true on either side,
    so a ``secret`` true→false transition never surfaces the old value.

    The ``*_changed`` flags compare plaintext but record only whether it
    changed. ``decrypt`` raises ``StoredSecretUnreadable`` for a secret it
    cannot read."""
    before_by_id = {str(entry["id"]): entry for entry in before}
    after_by_id = {str(entry["id"]): entry for entry in after}

    added = [
        _audit_view(entry, bool(entry.get("secret")))
        for key, entry in after_by_id.items()
        if key not in before_by_id
    ]
    removed = [
        _audit_view(entry, bool(entry.get("secret")))
        for key, entry in before_by_id.items()
        if key not in after_by_id
    ]
    updated: list[dict[str, Any]] = []
    for key, new in after_by_id.items():
        old = before_by_id.get(key)
        if old is None or dict(old) == dict(new):
            continue
        masked = bool(old.get("secret")) or bool(new.get("secret"))
        updated.append(
            {
                "id": key,
                "old": _audit_view(old, masked),
                "new": _audit_view(new, masked),
                "value_changed": _plaintext_changed(old, new, "value", decrypt),
                "fallback_changed": _plaintext_changed(old, new, "fallback", decrypt),
            }
        )
    if not (added or removed or updated):
        return None
    return {"added": added, "removed": removed, "updated": updated}
