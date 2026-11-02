"""A draft may declare how a connection signs in before its credential exists."""

from __future__ import annotations

from eneo.flows.http_transport.authored_config import (
    SECRET_SENTINEL,
    HttpAuthApiKey,
    HttpAuthBasicAuth,
    HttpAuthBearer,
    HttpAuthoredConfig,
)
from eneo.flows.http_transport.errors import HttpTransportError
from eneo.flows.http_transport.validator import (
    credential_missing,
    validate_authored_config,
)


def _errors(auth, *, credentials_required: bool) -> list[HttpTransportError]:
    return validate_authored_config(
        HttpAuthoredConfig(url="https://example.org/api", auth=auth),
        direction="input",
        method="GET",
        max_timeout=60.0,
        credentials_required=credentials_required,
    )


def test_a_draft_may_declare_an_auth_mode_whose_credential_is_not_entered_yet():
    auth = HttpAuthApiKey(header_name="X-API-Key", key="")

    assert credential_missing(auth)
    assert _errors(auth, credentials_required=False) == []
    assert _errors(auth, credentials_required=True) == [
        HttpTransportError.MISSING_AUTH_CREDENTIALS
    ]


def test_a_stored_or_entered_credential_is_not_missing():
    assert not credential_missing(HttpAuthBearer(token=SECRET_SENTINEL))
    assert not credential_missing(HttpAuthBasicAuth(username="svc", password=""))
    assert credential_missing(HttpAuthBasicAuth(username="", password=""))
