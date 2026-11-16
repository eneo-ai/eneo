"""Typed refusals of an OIDC sign-in.

They stay transport-neutral; ``DOMAIN_EXCEPTION_MAP`` gives each its status
and numeric code, and the string ``code`` lets both frontends explain it.
"""


class OidcSignInError(Exception):
    code: str = "oidc_sign_in_failed"


class OidcLoginUnavailableError(OidcSignInError):
    """The sign-in transaction store is missing or failed (503).

    Sign-in never continues without it: the transaction is what makes a
    callback single-use and carries the nonce and PKCE verifier.
    """

    code = "oidc_login_unavailable"

    def __init__(self, message: str = "Sign-in is temporarily unavailable."):
        super().__init__(message)


class OidcTransactionInvalidError(OidcSignInError):
    """No live sign-in transaction for this callback (400): it expired, was
    already used or was never started here."""

    code = "oidc_transaction_invalid"

    def __init__(
        self,
        message: str = (
            "Authorization session is invalid or has expired. "
            "Please restart the sign-in flow."
        ),
    ):
        super().__init__(message)


class OidcResponseNotVerifiedError(OidcSignInError):
    """The provider's response failed a check (401). It is never retried
    through a weaker path."""

    code = "oidc_response_not_verified"

    def __init__(self, message: str = "The sign-in response could not be verified."):
        super().__init__(message)
