"""HTTP Basic Authentication credentials value object.

Why Value Object:
- Immutable by nature (credentials don't change, they're replaced)
- No identity - two credentials with same values are equal
- Self-validating - ensures consistency at creation
- Encapsulates domain rules
"""

from dataclasses import dataclass
from urllib.parse import urlsplit

from yarl import URL

from eneo.websites.domain.source_url import normalize_url


class HttpAuthDestinationError(ValueError):
    """Stored credentials cannot safely be used for the requested destination."""

    def __init__(self) -> None:
        super().__init__(
            "HTTP authentication is not bound to this website URL. "
            "Re-enter the username and password, or remove authentication."
        )


@dataclass(frozen=True)
class HttpAuthCredentials:
    """Value Object representing HTTP Basic Authentication credentials.

    Security Design:
    - This object holds PLAINTEXT credentials temporarily during domain operations
    - Never persisted in plaintext - encryption happens at infrastructure boundary
    - Short-lived - exists only during request/crawl lifecycle
    - Origin-bound to prevent credential leakage across crawl destinations
    """

    username: str
    password: str
    auth_domain: str

    @staticmethod
    def origin_for_url(url: str) -> str:
        """Use the crawl transport's origin and IDNA rules after URL normalization."""
        normalized = normalize_url(url.strip())
        if normalized is None:
            raise ValueError("HTTP authentication requires an HTTP(S) URL")
        return str(URL(normalized).origin())

    @classmethod
    def require_destination(cls, auth_domain: str | None, url: str) -> None:
        """Check persisted binding before a worker decrypts any secret.

        Before origin binding, http_auth_domain stored only netloc. Those rows
        prove host/port ownership but cannot prove the original scheme. They
        remain usable only over HTTPS at that authority, without rewriting the
        binding. HTTP requires explicitly entered credentials with a full origin.
        """
        if not auth_domain:
            raise HttpAuthDestinationError()
        binding = auth_domain.strip()
        qualified = "://" in binding
        bound_url = binding if qualified else f"https://{binding}"
        try:
            parsed = urlsplit(bound_url)
            valid_binding = (
                parsed.path in {"", "/"}
                and not parsed.query
                and not parsed.fragment
                and cls.origin_for_url(bound_url) == cls.origin_for_url(url)
            )
        except ValueError:
            valid_binding = False
        if not valid_binding:
            raise HttpAuthDestinationError()

    def __post_init__(self):
        """Validate credentials meet business rules."""
        if not self.username or not self.username.strip():
            raise ValueError("HTTP auth username cannot be empty")

        if not self.password or not self.password.strip():
            raise ValueError("HTTP auth password cannot be empty")

        if not self.auth_domain or not self.auth_domain.strip():
            raise ValueError("HTTP auth domain cannot be empty")

    @classmethod
    def from_website_url(
        cls, username: str, password: str, website_url: str
    ) -> "HttpAuthCredentials":
        """Bind newly supplied credentials to the exact normalized HTTP origin.

        The existing auth_domain storage field carries the full origin for newly
        supplied credentials; older host-only values are never silently upgraded.

        Args:
            username: HTTP Basic Auth username
            password: HTTP Basic Auth password
            website_url: Website URL to bind the credentials to

        Returns:
            HttpAuthCredentials bound to the URL's scheme, host and effective port

        Raises:
            ValueError: If the URL is not a valid HTTP origin
        """
        return cls(
            username=username.strip(),
            password=password,
            auth_domain=cls.origin_for_url(website_url),
        )
