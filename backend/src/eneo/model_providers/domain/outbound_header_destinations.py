"""Where configured outbound headers may be sent.

Callers must pass the endpoint the request actually uses — the provider kwargs'
``api_base``, resolved through the same credentials-then-config precedence as
the request itself — never ``config["endpoint"]`` read directly. A check that
reads a different field approves one host while the request goes to another.

Rules:

- **An explicit endpoint is required.** An empty one means the vendor's public
  default, which is essentially never a deliberate place to send attributes.
- **URLs carrying credentials** (``user:pass@``) are refused, not stripped.
- **An optional deployment allow-list** narrows the destination further.
  Matching is exact: scheme; host case-insensitively after IDNA normalisation,
  with no suffix matching; port with the scheme default filled in; and path on
  ``/`` boundaries (``/v1`` admits ``/v1/chat``, not ``/v1beta``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

DestinationProblem = Literal[
    "no_endpoint", "invalid_endpoint", "credentials_in_url", "not_allowed"
]

_DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass(frozen=True)
class Destination:
    scheme: str
    host: str
    port: int
    path: str


class InvalidDestination(ValueError):
    pass


class CredentialsInDestination(InvalidDestination):
    pass


def parse_destination(url: str) -> Destination:
    """Normalise a URL for comparison. Raises ``InvalidDestination``."""
    # Messages never repeat the URL: a malformed one may carry credentials.
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError as exc:
        raise InvalidDestination("not a valid URL") from exc
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS or not parts.hostname:
        raise InvalidDestination("must be an absolute http or https URL")
    if parts.username is not None or parts.password is not None:
        raise CredentialsInDestination("must not contain credentials")
    try:
        host = parts.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise InvalidDestination("has an invalid host name") from exc
    return Destination(
        scheme=scheme,
        host=host,
        port=port or _DEFAULT_PORTS[scheme],
        path=parts.path.rstrip("/"),
    )


def without_credentials(url: str | None) -> str | None:
    """``url`` with any ``user:pass@`` removed, for audit records.

    Plain string handling rather than ``urlsplit``, which raises on some
    malformed authorities; this must never fail on what a provider stores.
    """
    if not url:
        return url
    scheme, separator, rest = url.partition("://")
    if not separator:
        return url
    ends = [index for index in (rest.find(char) for char in "/?#") if index != -1]
    end = min(ends, default=len(rest))
    authority = rest[:end]
    if "@" not in authority:
        return url
    return f"{scheme}{separator}{authority.rpartition('@')[2]}{rest[end:]}"


def parse_allow_list(entries: Sequence[str]) -> tuple[Destination, ...]:
    """Entries are validated when settings load, so parsing cannot fail here.

    Called for every request and embedding batch, so the parse is cached,
    keyed on the entries themselves."""
    return _parse_allow_list(tuple(entries))


@lru_cache(maxsize=8)
def _parse_allow_list(entries: tuple[str, ...]) -> tuple[Destination, ...]:
    return tuple(parse_destination(entry) for entry in entries)


def _admits(entry: Destination, destination: Destination) -> bool:
    if (entry.scheme, entry.host, entry.port) != (
        destination.scheme,
        destination.host,
        destination.port,
    ):
        return False
    return (
        not entry.path
        or destination.path == entry.path
        or destination.path.startswith(entry.path + "/")
    )


def destination_problem(
    endpoint: str | None, allowed: Sequence[Destination]
) -> DestinationProblem | None:
    """None when headers may be sent to ``endpoint``; otherwise why not."""
    if not endpoint or not endpoint.strip():
        return "no_endpoint"
    try:
        destination = parse_destination(endpoint)
    except CredentialsInDestination:
        return "credentials_in_url"
    except InvalidDestination:
        return "invalid_endpoint"
    if allowed and not any(_admits(entry, destination) for entry in allowed):
        return "not_allowed"
    return None
