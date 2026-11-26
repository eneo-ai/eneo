"""The authorization request Eneo sends the person's browser to."""

from collections.abc import Mapping
from urllib.parse import urlencode

from eneo.authentication.oidc.profile import OidcProfile
from eneo.authentication.oidc.transaction import OidcTransaction, code_challenge


def build_authorization_request(
    profile: OidcProfile,
    transaction: OidcTransaction,
    *,
    state: str,
    asking_for: Mapping[str, str] | None = None,
) -> str:
    """The authorization URL for a transaction that has been stored.

    State, nonce and PKCE S256 are always sent. A provider that does not know
    PKCE ignores the extra parameters (RFC 6749 3.1), so the challenge is never
    left out and never sent as ``plain``. ``asking_for`` is what a sign-in for
    MFA adds (``MfaRule.authorization_parameters``); it never replaces one of
    the parameters below.
    """
    params = {
        **(asking_for or {}),
        "client_id": profile.client_id,
        "response_type": "code",
        "redirect_uri": transaction.redirect_uri,
        "scope": " ".join(profile.scopes),
        "state": state,
        "nonce": transaction.nonce,
        "code_challenge": code_challenge(transaction.code_verifier),
        "code_challenge_method": "S256",
    }
    return f"{profile.authorization_endpoint}?{urlencode(params)}"
