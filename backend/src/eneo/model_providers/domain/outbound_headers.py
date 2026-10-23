"""Per-provider outbound HTTP headers.

An administrator configures headers on a model provider. Each value is literal
text mixed with ``{{token}}`` dynamic values, resolved per request from the
acting user's IdP-provisioned attributes. Eneo gives the values no meaning.

There is no template engine. Tokens are matched by one regex and each captured
name is a lookup in a closed registry: no attribute access, no calls, no
filters, no evaluation.

Two stages, deliberately separate:

- **Rejection** is the security control and is not configurable: a resolved
  value containing CR, LF or any other control character, or exceeding the
  size bounds, blocks the request. It is never repaired or truncated.
- **Encoding** is a compatibility choice declared per header: ``percent``
  (the default; the only mode that carries non-ASCII) or ``none`` (byte-exact,
  for credentials and exact-match values; non-ASCII blocks the request).

``on_missing`` governs absence only. Invalid values always block.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal
from urllib.parse import quote

from eneo.main.header_values import is_unsafe_header_char
from eneo.scim.domain.enterprise_user import enterprise_from_column
from eneo.tenants.provider_field_config import get_canonical_provider_type

if TYPE_CHECKING:
    from eneo.users.user import UserInDB

Encoding = Literal["percent", "none"]
OnMissing = Literal["omit", "fallback", "fail"]
Classification = Literal["identifying", "organisational"]
TokenSource = Literal["scim_enterprise", "external_id"]
HeaderState = Literal["resolved", "missing", "invalid"]
InvalidReason = Literal["control_character", "non_ascii", "value_too_long"]

ENCODINGS: tuple[Encoding, ...] = ("percent", "none")
ON_MISSING_POLICIES: tuple[OnMissing, ...] = ("omit", "fallback", "fail")

# v1 is verified end-to-end on the OpenAI-compatible self-hosted route only
# (spike, temp/prd.md Appendix B). Every other type refuses header
# configuration rather than risk a silent runtime no-op.
SUPPORTED_PROVIDER_TYPES: frozenset[str] = frozenset({"hosted_vllm"})

MAX_HEADERS = 10
MAX_NAME_BYTES = 64
MAX_CONFIGURED_VALUE_CHARS = 1024
MAX_RESOLVED_VALUE_BYTES = 1024
MAX_TOTAL_BYTES = 4096

_RESERVED_NAMES = (
    # Owned by HTTP, the client or the adapter.
    "Authorization",
    "Proxy-Authorization",
    "Proxy-Authenticate",
    "Cookie",
    "Set-Cookie",
    "Host",
    "Content-Length",
    "Content-Type",
    "Transfer-Encoding",
    "Connection",
    "Keep-Alive",
    "Upgrade",
    "Expect",
    "TE",
    "Trailer",
    "api-key",  # the Azure adapter sets it itself
    # Set by LiteLLM's HTTP client on every request (spike baseline).
    "Accept",
    "Accept-Encoding",
    "User-Agent",
    # Added by the OpenTelemetry propagators (main/observability.py) when the
    # request is sent — below the layer the send-time collision check sees.
    "traceparent",
    "tracestate",
    "baggage",
    # Kept free for a possible server-set tenant label; never admin-defined.
    "X-Eneo-Tenant-Id",
)
RESERVED_NAMES: frozenset[str] = frozenset(name.casefold() for name in _RESERVED_NAMES)

# SECURITY — single-pass substitution is load-bearing. re.sub with a
# replacement function never re-scans inserted text, so a provisioned value
# containing "{{...}}" passes through as a literal. This closes second-order
# injection by construction. Do NOT "improve" this into a resolve-until-stable
# loop.
TOKEN = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")
_HEADER_NAME = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")


@dataclass(frozen=True)
class DynamicValue:
    token: str
    source: TokenSource
    attribute: str
    classification: Classification
    resolve: Callable[[UserInDB], str | None] = field(repr=False, compare=False)


def _enterprise_attribute(attribute: str) -> Callable[[UserInDB], str | None]:
    def resolve(user: UserInDB) -> str | None:
        value = enterprise_from_column(user.scim_extensions).get(attribute)
        return value if isinstance(value, str) else None

    return resolve


def _external_id(user: UserInDB) -> str | None:
    return user.external_id


# A token earns a place by being stable, organisationally meaningful,
# single-valued and IdP-owned (not editable by the user or a tenant admin —
# which excludes email and username). Adding one takes a code change and a
# review: persisting an attribute and forwarding it are different decisions.
REGISTRY: Mapping[str, DynamicValue] = {
    value.token: value
    for value in (
        DynamicValue(
            "user.employeeNumber",
            "scim_enterprise",
            "employeeNumber",
            "identifying",
            _enterprise_attribute("employeeNumber"),
        ),
        DynamicValue(
            "user.externalId", "external_id", "externalId", "identifying", _external_id
        ),
        DynamicValue(
            "user.costCenter",
            "scim_enterprise",
            "costCenter",
            "organisational",
            _enterprise_attribute("costCenter"),
        ),
        DynamicValue(
            "user.department",
            "scim_enterprise",
            "department",
            "organisational",
            _enterprise_attribute("department"),
        ),
        DynamicValue(
            "user.division",
            "scim_enterprise",
            "division",
            "organisational",
            _enterprise_attribute("division"),
        ),
        DynamicValue(
            "user.organization",
            "scim_enterprise",
            "organization",
            "organisational",
            _enterprise_attribute("organization"),
        ),
    )
}


@dataclass(frozen=True)
class OutboundHeader:
    """A configured header with its value and fallback in plaintext.

    ``value`` and ``fallback`` are excluded from ``repr`` so a header can never
    reach a log line through string formatting.
    """

    id: str
    name: str
    value: str = field(repr=False)
    encoding: Encoding = "percent"
    secret: bool = False
    on_missing: OnMissing = "omit"
    fallback: str | None = field(default=None, repr=False)


class OutboundHeaderConfigError(ValueError):
    """A header configuration that must not be saved."""


def supports_outbound_headers(provider_type: str) -> bool:
    return get_canonical_provider_type(provider_type) in SUPPORTED_PROVIDER_TYPES


def header_classification(value: str) -> Classification | None:
    """The most sensitive classification among the tokens ``value`` uses.

    Stored with the header so an editor can show the matching notice for a
    secret header, whose template it never sees.
    """
    found = {
        REGISTRY[match.group(1)].classification
        for match in TOKEN.finditer(value)
        if match.group(1) in REGISTRY
    }
    if "identifying" in found:
        return "identifying"
    if "organisational" in found:
        return "organisational"
    return None


def validate_headers(headers: Sequence[OutboundHeader], provider_type: str) -> None:
    """Save-time validation: catch mistakes while the admin is looking.

    Not the security control — provisioned data changes after save, so the
    resolved value is checked again at send (``evaluate_headers``).
    """
    if not headers:
        return
    if not supports_outbound_headers(provider_type):
        raise OutboundHeaderConfigError(
            f"Provider type '{provider_type}' does not support outbound headers"
        )
    if len(headers) > MAX_HEADERS:
        raise OutboundHeaderConfigError(f"At most {MAX_HEADERS} headers per provider")

    seen: dict[str, str] = {}
    for header in headers:
        _validate_name(header.name)
        folded = header.name.casefold()
        if folded in seen:
            # HTTP field names are case-insensitive (RFC 9110 §5.1); two entries
            # would collapse into one field with a value nobody configured.
            raise OutboundHeaderConfigError(
                f"Headers '{seen[folded]}' and '{header.name}' are the same HTTP "
                "field; header names are case-insensitive"
            )
        seen[folded] = header.name
        _validate_value(header.name, header.value, header.encoding)
        if header.on_missing == "fallback" and not header.fallback:
            raise OutboundHeaderConfigError(
                f"Header '{header.name}' uses the fallback policy but has no fallback value"
            )
        if header.fallback:
            _validate_fallback(header.name, header.fallback, header.encoding)


def _validate_name(name: str) -> None:
    # fullmatch: `$` would also accept a name ending in a newline.
    if not _HEADER_NAME.fullmatch(name):
        raise OutboundHeaderConfigError(
            f"'{name}' is not a valid HTTP header name (RFC 9110 token)"
        )
    if len(name.encode("ascii")) > MAX_NAME_BYTES:
        raise OutboundHeaderConfigError(
            f"Header name '{name}' is longer than {MAX_NAME_BYTES} bytes"
        )
    if name.casefold() in RESERVED_NAMES:
        raise OutboundHeaderConfigError(f"'{name}' is a reserved header name")


def _validate_value(name: str, value: str, encoding: Encoding) -> None:
    if not value:
        raise OutboundHeaderConfigError(f"Header '{name}' needs a value")
    if len(value) > MAX_CONFIGURED_VALUE_CHARS:
        raise OutboundHeaderConfigError(
            f"Header '{name}' value is longer than {MAX_CONFIGURED_VALUE_CHARS} characters"
        )
    for match in TOKEN.finditer(value):
        if match.group(1) not in REGISTRY:
            raise OutboundHeaderConfigError(
                f"Header '{name}' uses unknown dynamic value '{{{{{match.group(1)}}}}}'"
            )
    literal = TOKEN.sub("", value)
    if "{{" in literal or "}}" in literal:
        raise OutboundHeaderConfigError(
            f"Header '{name}' has a malformed dynamic value; use {{{{token}}}}"
        )
    _validate_literal(name, "value", literal, encoding)


def _validate_fallback(name: str, fallback: str, encoding: Encoding) -> None:
    if len(fallback) > MAX_CONFIGURED_VALUE_CHARS:
        raise OutboundHeaderConfigError(
            f"Header '{name}' fallback is longer than {MAX_CONFIGURED_VALUE_CHARS} characters"
        )
    if TOKEN.search(fallback) or "{{" in fallback or "}}" in fallback:
        raise OutboundHeaderConfigError(
            f"Header '{name}' fallback cannot contain dynamic values; it is encoded like the value"
        )
    _validate_literal(name, "fallback", fallback, encoding)


def _validate_literal(name: str, part: str, literal: str, encoding: Encoding) -> None:
    if any(is_unsafe_header_char(ch) for ch in literal):
        raise OutboundHeaderConfigError(
            f"Header '{name}' {part} contains a control character"
        )
    if encoding == "none" and not _is_printable_ascii(literal):
        raise OutboundHeaderConfigError(
            f"Header '{name}' {part} must be printable ASCII when encoding is 'none'"
        )


def _is_printable_ascii(value: str) -> bool:
    return all(0x20 <= ord(ch) <= 0x7E for ch in value)


@dataclass(frozen=True)
class HeaderOutcome:
    """What one configured header does for one user, at send or in preview."""

    name: str
    secret: bool
    state: HeaderState
    policy: OnMissing | None = None
    """The missing-value policy applied; only set when ``state == "missing"``."""
    wire_value: str | None = field(default=None, repr=False)
    """The encoded value to send; None when the header is omitted or blocks."""
    reason: InvalidReason | None = None
    missing_tokens: tuple[str, ...] = ()

    @property
    def blocks(self) -> bool:
        return self.state == "invalid" or (
            self.state == "missing" and self.policy == "fail"
        )


def evaluate_headers(
    headers: Sequence[OutboundHeader], user: UserInDB | None
) -> list[HeaderOutcome]:
    """Resolve every configured header for ``user``. Pure; raises nothing.

    ``user`` is None for contexts with no acting user; every token is then
    missing. A service API key's synthetic user has no provisioned attributes,
    so the same holds for it.
    """
    return [_evaluate(header, user) for header in headers]


def _evaluate(header: OutboundHeader, user: UserInDB | None) -> HeaderOutcome:
    missing: list[str] = []

    def lookup(match: re.Match[str]) -> str:
        token = match.group(1)
        entry = REGISTRY.get(token)
        resolved = (
            entry.resolve(user) if entry is not None and user is not None else None
        )
        if not resolved:
            missing.append(token)
            return ""
        return resolved

    resolved_value = TOKEN.sub(lookup, header.value)

    if missing:
        # One unresolved token applies the policy to the whole header: a
        # partially substituted value ("dept-") is never emitted.
        tokens = tuple(dict.fromkeys(missing))
        if header.on_missing == "fallback" and header.fallback:
            wire, reason = _to_wire(header.fallback, header.encoding)
            if reason is not None:
                return HeaderOutcome(
                    header.name,
                    header.secret,
                    "invalid",
                    reason=reason,
                    missing_tokens=tokens,
                )
            return HeaderOutcome(
                header.name,
                header.secret,
                "missing",
                policy="fallback",
                wire_value=wire,
                missing_tokens=tokens,
            )
        policy: OnMissing = "fail" if header.on_missing == "fail" else "omit"
        return HeaderOutcome(
            header.name, header.secret, "missing", policy=policy, missing_tokens=tokens
        )

    wire, reason = _to_wire(resolved_value, header.encoding)
    if reason is not None:
        return HeaderOutcome(header.name, header.secret, "invalid", reason=reason)
    return HeaderOutcome(header.name, header.secret, "resolved", wire_value=wire)


def _to_wire(value: str, encoding: Encoding) -> tuple[str, InvalidReason | None]:
    """Reject, then encode. Rejection is never skipped or softened."""
    if any(is_unsafe_header_char(ch) for ch in value):
        return "", "control_character"
    if encoding == "none":
        if not _is_printable_ascii(value):
            return "", "non_ascii"
        wire = value
    else:
        # The same tail as MCP identity headers; receivers call
        # urllib.parse.unquote (or equivalent) to recover the value.
        wire = quote(value, safe=" @,")
    if len(wire.encode("ascii")) > MAX_RESOLVED_VALUE_BYTES:
        return "", "value_too_long"
    return wire, None


class OutboundHeadersBlocked(Exception):
    """The request must not be sent. Carries no header value, by design."""

    def __init__(self, header_name: str | None, reason: str) -> None:
        super().__init__(reason)
        self.header_name = header_name
        self.reason = reason


def request_headers(outcomes: Sequence[HeaderOutcome]) -> dict[str, str]:
    """The headers to send, or ``OutboundHeadersBlocked``.

    Invalidity and a ``fail`` policy block the whole request; there is no
    "send it without the headers" path.
    """
    for outcome in outcomes:
        if outcome.state == "invalid":
            raise OutboundHeadersBlocked(outcome.name, outcome.reason or "invalid")
        if outcome.blocks:
            raise OutboundHeadersBlocked(outcome.name, "missing_required_value")
    headers = {
        outcome.name: outcome.wire_value
        for outcome in outcomes
        if outcome.wire_value is not None
    }
    total = sum(len(name) + len(value) for name, value in headers.items())
    if total > MAX_TOTAL_BYTES:
        raise OutboundHeadersBlocked(None, "total_size_exceeded")
    return headers
