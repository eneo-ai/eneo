import json
import logging
import os
import sys
from typing import Optional
from urllib.parse import urlparse

from intric.definitions import ROOT_DIR
from pydantic import computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MANIFEST_LOCATION = f"{ROOT_DIR}/.release-please-manifest.json"


def validate_public_origin(origin: str | None) -> str | None:
    """
    Validate and normalize public origin.

    Rules:
    - Must be HTTPS (production security)
    - Must have hostname
    - No path, query, or fragment allowed
    - Normalize: lowercase hostname, strip trailing slash

    Args:
        origin: Raw origin string (e.g., "https://Example.com/")

    Returns:
        str | None: Normalized origin or None if input was None

    Raises:
        ValueError: Invalid origin format

    Examples:
        >>> validate_public_origin("https://Stockholm.Eneo.se/")
        "https://stockholm.eneo.se"

        >>> validate_public_origin("http://insecure.com")
        ValueError: public_origin must use https://
    """
    if origin is None:
        return None

    # Explicitly reject empty string (after stripping whitespace)
    origin = origin.strip()
    if not origin:
        raise ValueError("public_origin cannot be an empty string")
    parsed = urlparse(origin)

    # Validate HTTPS scheme (allow http://localhost for development)
    is_localhost = parsed.hostname in ("localhost", "127.0.0.1")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and is_localhost):
        raise ValueError(
            f"public_origin must use https:// (or http://localhost for development), got: {origin}"
        )

    # Validate hostname exists
    if not parsed.hostname:
        raise ValueError(f"public_origin missing hostname: {origin}")

    # Validate no path (except "/" which we'll strip)
    if parsed.path not in ("", "/"):
        raise ValueError(
            f"public_origin must not include path: {origin}"
        )

    # Validate no query or fragment
    if parsed.query or parsed.fragment:
        raise ValueError(
            f"public_origin must not include query or fragment: {origin}"
        )

    # Normalize: lowercase hostname, preserve non-default port
    host = parsed.hostname.lower()

    # Preserve scheme for localhost (http allowed), otherwise use https
    scheme = parsed.scheme if is_localhost else "https"

    # Preserve non-default port (443 for https, 80 for http)
    default_port = 443 if scheme == "https" else 80
    port = f":{parsed.port}" if parsed.port and parsed.port != default_port else ""

    return f"{scheme}://{host}{port}"


def _set_app_version():
    try:
        with open(MANIFEST_LOCATION) as f:
            manifest_data = json.load(f)

        version = manifest_data["."]
        if os.environ.get("DEV", False):
            return f"{version}-dev"

        return version
    except FileNotFoundError:
        return "DEV"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    app_version: str = _set_app_version()

    # OpenAPI-only mode flag
    openapi_only_mode: bool = False

    # Api keys and model urls
    infinity_url: Optional[str] = None
    vllm_model_url: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    ovhcloud_api_key: Optional[str] = None
    mistral_api_key: Optional[str] = None
    flux_api_key: Optional[str] = None
    tavily_api_key: Optional[str] = None
    vllm_api_key: Optional[str] = None
    berget_api_key: Optional[str] = None
    intric_marketplace_api_key: Optional[str] = None
    intric_marketplace_url: Optional[str] = None
    intric_super_api_key: Optional[str] = None
    intric_super_duper_api_key: Optional[str] = None

    # Infrastructure dependencies
    postgres_user: str
    postgres_host: str
    postgres_password: str
    postgres_port: int
    postgres_db: str
    redis_host: str
    redis_port: int

    # Background worker configuration
    worker_max_jobs: int = 20
    tenant_worker_concurrency_limit: int = 4
    tenant_worker_semaphore_ttl_seconds: int = 60 * 60 * 5  # 5 hour safety window
    tenant_worker_retry_delay_seconds: int = 30

    # Federation per tenant feature flag
    federation_per_tenant_enabled: bool = False

    # OIDC redirect safety controls
    oidc_state_ttl_seconds: int = 600
    oidc_redirect_grace_period_seconds: int = 900
    strict_oidc_redirect_validation: bool = True
    oidc_clock_leeway_seconds: int = 120

    # Generic OIDC config (renamed from MOBILITYGUARD_*)
    oidc_discovery_endpoint: Optional[str] = None
    oidc_client_id: Optional[str] = None
    oidc_client_secret: Optional[str] = None
    oidc_tenant_id: Optional[str] = None  # For backward compat with user creation

    # Public-facing origin for OIDC redirect_uri (single-tenant fallback)
    # This is the externally-reachable URL for the application
    # May be a proxy URL (e.g., https://m00-https-eneo-test.login.sundsvall.se)
    # or a direct URL (e.g., https://eneo.sundsvall.se)
    # Must match what users see in their browser and what's registered in IdP
    public_origin: Optional[str] = None

    # DEPRECATED: Mobilityguard (use OIDC_* instead - will be removed in v3.0)
    mobilityguard_discovery_endpoint: Optional[str] = None
    mobilityguard_client_id: Optional[str] = None
    mobilityguard_client_secret: Optional[str] = None
    mobilityguard_tenant_id: Optional[str] = None

    # Max sizes
    upload_file_to_session_max_size: int
    upload_image_to_session_max_size: int
    upload_max_file_size: int
    transcription_max_file_size: int
    max_in_question: int

    # Azure models
    using_azure_models: bool = False
    azure_api_key: Optional[str] = None
    azure_endpoint: Optional[str] = None
    azure_api_version: Optional[str] = None

    # Feature flags
    using_access_management: bool = True
    using_iam: bool = False
    using_image_generation: bool = False

    # Security
    api_prefix: str
    api_key_length: int
    api_key_header_name: str
    jwt_audience: str
    jwt_issuer: str
    jwt_expiry_time: int
    jwt_algorithm: str
    jwt_secret: str
    jwt_token_prefix: str
    url_signing_key: str

    # Dev
    testing: bool = False
    dev: bool = False

    # Crawl - Scrapy crawler settings
    crawl_max_length: int = 60 * 60 * 4  # 4 hour crawls max (in seconds)
    closespider_itemcount: int = 20000  # Maximum number of pages to crawl per website
    obey_robots: bool = True  # Respect robots.txt rules
    autothrottle_enabled: bool = True  # Enable automatic request throttling
    using_crawl: bool = True  # Enable/disable crawling feature globally

    # Worker configuration
    worker_max_concurrent_jobs: int = (
        20  # Maximum number of concurrent jobs the worker can process
    )

    # Crawl retry configuration
    crawl_page_max_retries: int = 3  # Maximum retries for failed pages during crawl
    crawl_page_retry_delay: float = (
        1.0  # Initial retry delay in seconds (exponential backoff)
    )

    # Migration
    migration_auto_recalc_threshold: int = (
        30  # Auto-recalculate usage stats for migrations <= this threshold
    )

    # integration callback
    oauth_callback_url: Optional[str] = None

    # Confluence
    confluence_client_id: Optional[str] = None
    confluence_client_secret: Optional[str] = None

    # Sharepoint
    sharepoint_client_id: Optional[str] = None
    sharepoint_client_secret: Optional[str] = None

    # Generic encryption key for sensitive data (HTTP auth, tenant API keys, etc.)
    # Required for encrypting HTTP auth credentials, tenant API credentials, etc.
    # Generate with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
    encryption_key: str

    # Tenant credential management
    tenant_credentials_enabled: bool = False

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_vars(cls, values):
        """Auto-migrate MOBILITYGUARD_* to OIDC_* with deprecation warnings."""
        migrations = [
            ("oidc_discovery_endpoint", "mobilityguard_discovery_endpoint"),
            ("oidc_client_id", "mobilityguard_client_id"),
            ("oidc_client_secret", "mobilityguard_client_secret"),
            ("oidc_tenant_id", "mobilityguard_tenant_id"),
        ]

        for new_name, old_name in migrations:
            # If new value not set but old value exists
            if not values.get(new_name) and values.get(old_name):
                values[new_name] = values[old_name]
                logging.warning(
                    f"DEPRECATION: Using {old_name.upper()}. "
                    f"Please update to {new_name.upper()} in your .env file. "
                    f"Legacy variables will be removed in v3.0"
                )

        return values

    @model_validator(mode="after")
    def validate_worker_settings(self):
        """Ensure worker-related configuration values are sane."""
        if self.worker_max_jobs <= 0:
            logging.error(
                "ENEO_WORKER_MAX_JOBS must be greater than zero. Current value: %s",
                self.worker_max_jobs,
            )
            sys.exit(1)

        if self.tenant_worker_concurrency_limit < 0:
            logging.error(
                "TENANT_WORKER_CONCURRENCY_LIMIT cannot be negative. Current value: %s",
                self.tenant_worker_concurrency_limit,
            )
            sys.exit(1)

        if self.tenant_worker_semaphore_ttl_seconds <= 0:
            logging.error(
                "TENANT_WORKER_SEMAPHORE_TTL_SECONDS must be greater than zero. Current value: %s",
                self.tenant_worker_semaphore_ttl_seconds,
            )
            sys.exit(1)

        if self.tenant_worker_semaphore_ttl_seconds < self.crawl_max_length:
            logging.error(
                "TENANT_WORKER_SEMAPHORE_TTL_SECONDS (%s) is shorter than CRAWL_MAX_LENGTH (%s)."
                " Increase the TTL to cover the longest crawl duration to avoid leaking slots.",
                self.tenant_worker_semaphore_ttl_seconds,
                self.crawl_max_length,
            )
            sys.exit(1)

        if self.tenant_worker_retry_delay_seconds < 0:
            logging.error(
                "TENANT_WORKER_RETRY_DELAY_SECONDS cannot be negative. Current value: %s",
                self.tenant_worker_retry_delay_seconds,
            )
            sys.exit(1)

        if self.oidc_state_ttl_seconds <= 0:
            logging.error(
                "OIDC_STATE_TTL_SECONDS must be greater than zero. Current value: %s",
                self.oidc_state_ttl_seconds,
            )
            sys.exit(1)

        if self.oidc_redirect_grace_period_seconds < 0:
            logging.error(
                "OIDC_REDIRECT_GRACE_PERIOD_SECONDS cannot be negative. Current value: %s",
                self.oidc_redirect_grace_period_seconds,
            )
            sys.exit(1)

        if self.oidc_clock_leeway_seconds < 0:
            logging.error(
                "OIDC_CLOCK_LEEWAY_SECONDS cannot be negative. Current value: %s",
                self.oidc_clock_leeway_seconds,
            )
            sys.exit(1)

        if (
            self.oidc_redirect_grace_period_seconds
            and self.oidc_redirect_grace_period_seconds > self.oidc_state_ttl_seconds
        ):
            logging.warning(
                "OIDC_REDIRECT_GRACE_PERIOD_SECONDS (%s) exceeds state TTL (%s). "
                "Grace period will be capped to TTL to avoid accepting expired state.",
                self.oidc_redirect_grace_period_seconds,
                self.oidc_state_ttl_seconds,
            )

        return self

    @model_validator(mode="after")
    def validate_public_origin_format(self):
        """Validate and normalize public_origin."""
        if self.public_origin:
            try:
                self.public_origin = validate_public_origin(self.public_origin)
            except ValueError as e:
                logging.error(
                    f"Invalid PUBLIC_ORIGIN configuration: {e}\n"
                    f"Example: PUBLIC_ORIGIN=https://eneo.sundsvall.se"
                )
                sys.exit(1)
        return self

    @computed_field
    @property
    def sync_database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:"
            f"{self.postgres_password}@{self.postgres_host}:"
            f"{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:"
            f"{self.postgres_password}@{self.postgres_host}:"
            f"{self.postgres_port}/{self.postgres_db}"
        )


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get settings singleton, creating it if needed.

    Returns:
        Settings: The application settings instance.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def set_settings(settings: Settings) -> None:
    """Override settings (primarily for testing).

    Args:
        settings: The Settings instance to use.
    """
    global _settings
    _settings = settings


def reset_settings() -> None:
    """Reset settings to None (for test cleanup)."""
    global _settings
    _settings = None


def __getattr__(name: str):
    """Support backward compatibility for SETTINGS access.

    This allows existing code using `from intric.main.config import SETTINGS`
    to continue working during migration to get_settings().
    """
    if name == "SETTINGS":
        return get_settings()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_loglevel():
    loglevel = os.getenv("LOGLEVEL", "INFO")

    match loglevel:
        case "INFO":
            return logging.INFO
        case "WARNING":
            return logging.WARNING
        case "ERROR":
            return logging.ERROR
        case "CRITICAL":
            return logging.CRITICAL
        case "DEBUG":
            return logging.DEBUG
        case _:
            return logging.INFO
