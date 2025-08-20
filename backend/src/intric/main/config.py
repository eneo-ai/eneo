import json
import logging
import os
import re
import hashlib
from datetime import datetime
from difflib import get_close_matches
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

from intric.definitions import ROOT_DIR
from pydantic import computed_field, field_validator, model_validator
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

    # Crawl
    crawl_max_length: int = 60 * 60 * 4  # 4 hour crawls max
    closespider_itemcount: int = 20000
    obey_robots: bool = True
    autothrottle_enabled: bool = True
    using_crawl: bool = True

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

    # Validation methods
    @field_validator('postgres_port', 'redis_port')
    @classmethod
    def validate_ports(cls, v):
        """Validate port numbers are in valid range."""
        if v is not None and (v < 1 or v > 65535):
            raise ValueError(f"Port must be between 1 and 65535, got {v}")
        return v

    @field_validator('infinity_url', 'vllm_model_url', 'intric_marketplace_url', 
                    'mobilityguard_discovery_endpoint', 'azure_endpoint', 'oauth_callback_url')
    @classmethod
    def validate_urls(cls, v):
        """Validate URL format for URL fields."""
        if v is not None and v.strip():
            try:
                parsed = urlparse(v)
                if not parsed.scheme or not parsed.netloc:
                    # Don't fail, just log a warning - this will be handled in logging
                    pass
            except Exception:
                # Don't fail on URL parsing errors to maintain backwards compatibility
                pass
        return v

    @model_validator(mode='after')
    def validate_conditional_configs(self) -> 'Settings':
        """Validate configurations that depend on each other."""
        # These validations only log warnings, don't raise errors to maintain backwards compatibility
        return self

    def check(self) -> Dict[str, Any]:
        """
        Check configuration and return structured results.
        Returns dict with 'errors', 'warnings', and 'features' keys.
        """
        errors = []
        warnings = []
        features = {}

        # Check Azure configuration consistency
        if self.using_azure_models:
            if not self.azure_api_key:
                warnings.append("Azure models enabled but AZURE_API_KEY not set")
            if not self.azure_endpoint:
                warnings.append("Azure models enabled but AZURE_ENDPOINT not set")
            if not self.azure_api_version:
                warnings.append("Azure models enabled but AZURE_API_VERSION not set")

        # Check MobilityGuard configuration
        mobility_guard_configs = [
            self.mobilityguard_discovery_endpoint,
            self.mobilityguard_client_id, 
            self.mobilityguard_client_secret
        ]
        mobility_guard_set = [x for x in mobility_guard_configs if x]
        if 0 < len(mobility_guard_set) < len(mobility_guard_configs):
            warnings.append("MobilityGuard partially configured - some required fields are missing")

        # Enhanced unknown environment variable detection with suggestions
        unknown_vars = self._detect_unknown_variables()
        if unknown_vars:
            warnings.append(f"Unknown environment variables detected (possible typos): {', '.join(unknown_vars)}")

        # Determine enabled features
        features.update({
            'ai_models': {
                'openai': bool(self.openai_api_key),
                'anthropic': bool(self.anthropic_api_key),
                'azure': self.using_azure_models and bool(self.azure_api_key),
                'mistral': bool(self.mistral_api_key),
                'ovhcloud': bool(self.ovhcloud_api_key),
                'tavily': bool(self.tavily_api_key),
                'flux': bool(self.flux_api_key),
                'vllm': bool(self.vllm_api_key),
            },
            'auth_providers': {
                'mobilityguard': bool(self.mobilityguard_client_id and self.mobilityguard_discovery_endpoint),
            },
            'integrations': {
                'confluence': bool(self.confluence_client_id),
                'sharepoint': bool(self.sharepoint_client_id),
                'crawling': self.using_crawl,
                'image_generation': self.using_image_generation,
            },
            'infrastructure': {
                'postgres': f"{self.postgres_host}:{self.postgres_port}",
                'redis': f"{self.redis_host}:{self.redis_port}",
            }
        })

        return {
            'errors': errors,
            'warnings': warnings,
            'features': features,
            'unknown_vars': unknown_vars,
            'config_hash': self.get_config_hash(),
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }

    def get_summary(self, mask_secrets: bool = True) -> Dict[str, Any]:
        """
        Get a configuration summary with optional secret masking.
        Use this for startup logging and admin endpoints.
        """
        def mask_secret(value: Optional[str]) -> str:
            """
            Improved secret masking - fixed length for security.
            Shows ****abc123 format for secrets >= 12 chars, otherwise all stars.
            """
            if not value:
                return "Not set"
            if not mask_secrets:
                return value
            if len(value) < 12:
                return "****" + "*" * min(len(value), 4)  # Fixed length, no info leak
            return "****" + value[-4:]  # Show last 4 chars only for longer secrets

        summary = {
            'app_version': self.app_version,
            'environment': 'development' if self.dev else 'production',
            'ai_models': {
                'openai': mask_secret(self.openai_api_key),
                'anthropic': mask_secret(self.anthropic_api_key),
                'azure': mask_secret(self.azure_api_key) if self.using_azure_models else "Disabled",
                'mistral': mask_secret(self.mistral_api_key),
                'ovhcloud': mask_secret(self.ovhcloud_api_key),
                'tavily': mask_secret(self.tavily_api_key),
                'flux': mask_secret(self.flux_api_key),
                'vllm': mask_secret(self.vllm_api_key),
            },
            'features': {
                'access_management': self.using_access_management,
                'iam': self.using_iam,
                'image_generation': self.using_image_generation,
                'crawling': self.using_crawl,
                'azure_models': self.using_azure_models,
                'testing_mode': self.testing,
                'dev_mode': self.dev,
            },
            'auth_providers': {
                'mobilityguard': "Configured" if (self.mobilityguard_client_id and self.mobilityguard_discovery_endpoint) else "Not configured",
            },
            'database': f"postgres://{self.postgres_host}:{self.postgres_port}/{self.postgres_db}",
            'redis': f"{self.redis_host}:{self.redis_port}",
        }

        return summary
    
    def _detect_unknown_variables(self) -> List[str]:
        """
        Detect unknown environment variables that might be typos.
        Provides suggestions for similar variable names.
        """
        # Get all known field names from the Settings model
        known_fields = set()
        for field_name in self.model_fields:
            # Add both the field name and uppercase version
            known_fields.add(field_name.upper())
            known_fields.add(field_name)
        
        # Add common environment variable patterns
        known_patterns = {
            'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'AZURE_API_KEY', 'MISTRAL_API_KEY',
            'POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_HOST', 'POSTGRES_PORT', 'POSTGRES_DB',
            'REDIS_HOST', 'REDIS_PORT',
            'MOBILITYGUARD_DISCOVERY_ENDPOINT', 'MOBILITYGUARD_CLIENT_ID', 'MOBILITYGUARD_CLIENT_SECRET',
            'JWT_SECRET', 'JWT_ISSUER', 'JWT_AUDIENCE', 'TESTING', 'DEV',
            'LOGLEVEL', 'PATH', 'HOME', 'USER', 'TZ', 'NODE_ENV'  # Common system vars to ignore
        }
        known_fields.update(known_patterns)
        
        unknown_vars = []
        suggestions = {}
        
        # Check environment variables
        for env_var in os.environ:
            # Skip system variables and common non-config vars
            if env_var.startswith(('_', 'LANG', 'LC_', 'TERM', 'SHELL', 'PWD', 'OLDPWD')):
                continue
            
            # Skip development tool environment variables
            if env_var.startswith(('VSCODE_', 'REMOTE_CONTAINERS', 'NVM_', 'PIPX_', 'GIT_', 'PYTHON_')):
                continue
                
            # Skip common system/shell variables
            common_system_vars = {
                'COLORTERM', 'HOSTNAME', 'VIRTUAL_ENV', 'WAYLAND_DISPLAY', 'GPG_KEY', 
                'LS_COLORS', 'DISPLAY', 'SHLVL', 'PROMPT_DIRTRIM', 'XDG_RUNTIME_DIR',
                'BROWSER', 'EDITOR', 'PAGER', 'MANPATH', 'INFOPATH'
            }
            if env_var in common_system_vars:
                continue
                
            if env_var not in known_fields:
                # Look for close matches
                close_matches = get_close_matches(env_var, known_fields, n=3, cutoff=0.6)
                if close_matches:
                    suggestions[env_var] = close_matches
                unknown_vars.append(env_var)
        
        # Store suggestions for later use (could be added to warnings)
        self._variable_suggestions = suggestions
        return unknown_vars
    
    def get_config_hash(self) -> str:
        """
        Generate a SHA256 hash of non-secret configuration for drift detection.
        Excludes sensitive fields and includes only configuration that affects behavior.
        """
        # Get model dump excluding sensitive fields
        sensitive_fields = {
            'openai_api_key', 'anthropic_api_key', 'azure_api_key', 'mistral_api_key',
            'ovhcloud_api_key', 'flux_api_key', 'tavily_api_key', 'vllm_api_key',
            'postgres_password', 'jwt_secret', 'url_signing_key',
            'mobilityguard_client_secret', 'confluence_client_secret', 
            'sharepoint_client_secret', 'intric_super_api_key', 'intric_super_duper_api_key'
        }
        
        config_dict = self.model_dump(exclude=sensitive_fields)
        
        # Sort keys for consistent hashing
        config_json = json.dumps(config_dict, sort_keys=True, default=str)
        return hashlib.sha256(config_json.encode('utf-8')).hexdigest()[:16]  # First 16 chars for readability


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
