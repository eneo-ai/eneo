"""HTTP Basic Authentication credentials value object.

Why Value Object:
- Immutable by nature (credentials don't change, they're replaced)
- No identity - two credentials with same values are equal
- Self-validating - ensures consistency at creation
- Encapsulates domain rules
"""

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class HttpAuthCredentials:
    """Value Object representing HTTP Basic Authentication credentials.

    Security Design:
    - This object holds PLAINTEXT credentials temporarily during domain operations
    - Never persisted in plaintext - encryption happens at infrastructure boundary
    - Short-lived - exists only during request/crawl lifecycle
    - Domain-locked to prevent credential leakage
    """

    username: str
    password: str
    auth_domain: str  # Credentials are only valid for this exact domain

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
        """Factory method to create credentials with auto-extracted domain.

        Why: credentials must only ever be sent to the exact domain they
        were registered for.
        Extracting domain from website URL ensures credentials only apply to intended site.

        Args:
            username: HTTP Basic Auth username
            password: HTTP Basic Auth password
            website_url: Full website URL to extract domain from

        Returns:
            HttpAuthCredentials with domain extracted from URL

        Raises:
            ValueError: If domain cannot be extracted from URL
        """
        parsed_uri = urlparse(website_url)
        auth_domain = parsed_uri.netloc

        if not auth_domain:
            raise ValueError(f"Cannot extract domain from URL: {website_url}")

        return cls(
            username=username.strip(), password=password, auth_domain=auth_domain
        )
