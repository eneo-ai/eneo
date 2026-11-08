"""The authorization request Eneo sends the person's browser to."""

import base64
import hashlib
from urllib.parse import urlencode

from eneo.authentication.oidc.profile import OidcProfile
from eneo.authentication.oidc.transaction import OidcTransaction


def code_challenge(code_verifier: str) -> str:
    """The PKCE S256 challenge of a verifier (RFC 7636 4.2)."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def build_authorization_request(
    profile: OidcProfile, transaction: OidcTransaction, *, state: str
) -> str:
    """The authorization URL for a transaction that has been stored.

    State, nonce and PKCE S256 are always sent. A provider that does not know
    PKCE ignores the extra parameters (RFC 6749 3.1), so the challenge is never
    left out and never sent as ``plain``.
    """
    params = {
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
