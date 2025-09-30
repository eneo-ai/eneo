import json
import logging
import os
from typing import Optional

from intric.definitions import ROOT_DIR
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

MANIFEST_LOCATION = f"{ROOT_DIR}/.release-please-manifest.json"


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

    # Mobilityguard
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

    # Crawl - General settings (applies to all crawler engines)
    crawl_max_length: int = 60 * 60 * 4  # 4 hour crawls max (in seconds)
    closespider_itemcount: int = 20000  # Maximum number of pages to crawl per website
    obey_robots: bool = True  # Respect robots.txt rules
    autothrottle_enabled: bool = True  # Enable automatic request throttling
    using_crawl: bool = True  # Enable/disable crawling feature globally

    # Crawl4AI-specific settings
    # Performance optimization
    crawl4ai_text_only_mode: bool = True  # Enable text-only mode for faster crawls (disables images/GPU)
    crawl4ai_light_mode: bool = True  # Enable light mode to reduce browser overhead

    # Memory and concurrency management
    crawl4ai_memory_threshold_percent: float = 75.0  # Auto-pause crawls when system memory exceeds this %
    crawl4ai_max_concurrent_sessions: int = 5  # Max concurrent pages in sitemap crawls (controls parallelism)
    crawl4ai_memory_check_interval: float = 1.0  # How often to check system memory (seconds)

    # Rate limiting (prevents server blocking)
    crawl4ai_rate_limit_delay_min: float = 1.0  # Minimum delay between requests to same domain (seconds)
    crawl4ai_rate_limit_delay_max: float = 3.0  # Maximum delay between requests to same domain (seconds)
    crawl4ai_max_retries: int = 3  # Maximum retry attempts on rate-limit errors (429, 503)

    # Monitoring
    crawl4ai_enable_monitor: bool = True  # Enable live crawl progress display in worker terminal
    crawl4ai_show_progress_messages: bool = False  # Show [FETCH] [SCRAPE] [COMPLETE] messages

    # Content extraction configuration
    crawl4ai_word_threshold: int = 10  # Minimum word count for valid page content
    crawl4ai_table_score_threshold: int = 5  # Minimum score for table extraction (lower = more tables)

    # File download configuration
    crawl4ai_download_timeout: int = 15  # Seconds to wait for file downloads to complete
    crawl4ai_max_file_size_mb: int = 50  # Maximum file size in MB for downloaded files

    # Worker configuration
    worker_max_concurrent_jobs: int = 20  # Maximum number of concurrent jobs the worker can process

    # integration callback
    oauth_callback_url: Optional[str] = None

    # Confluence
    confluence_client_id: Optional[str] = None
    confluence_client_secret: Optional[str] = None

    # Sharepoint
    sharepoint_client_id: Optional[str] = None
    sharepoint_client_secret: Optional[str] = None

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


SETTINGS = Settings()


def get_settings():
    return SETTINGS


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
