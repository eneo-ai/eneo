"""
Centralized configuration for provider-specific credential field requirements.

This module defines which fields are required for each LLM provider's credentials.
Used by routers, validators, and domain models to ensure consistency.

Each field definition has:
  - name: field identifier (used as key in credentials/config dicts)
  - required: whether the field must be provided
  - secret: whether the field contains sensitive data (renders as password input)
  - in: "credentials" or "config" — where the value is stored in the API payload
"""

from typing import Any, Set, TypedDict


class FieldDefinition(TypedDict):
    name: str
    required: bool
    secret: bool
    in_: str  # "credentials" or "config"


# Canonical alias mapping — maps variant names to their canonical provider type
PROVIDER_ALIASES: dict[str, str] = {
    "vllm": "hosted_vllm",
}


def get_canonical_provider_type(provider: str) -> str:
    """Map a provider name to its canonical type (e.g. 'vllm' -> 'hosted_vllm')."""
    return PROVIDER_ALIASES.get(provider.lower(), provider.lower())


# Default fields used for any provider not explicitly configured
DEFAULT_FIELDS: list[FieldDefinition] = [
    {"name": "api_key", "required": True, "secret": True, "in_": "credentials"},
    {"name": "endpoint", "required": False, "secret": False, "in_": "config"},
]

# Provider-specific field definitions (overrides DEFAULT_FIELDS entirely)
PROVIDER_FIELD_DEFINITIONS: dict[str, list[FieldDefinition]] = {
    "azure": [
        {"name": "api_key", "required": True, "secret": True, "in_": "credentials"},
        {"name": "endpoint", "required": True, "secret": False, "in_": "config"},
        {"name": "api_version", "required": True, "secret": False, "in_": "config"},
        {"name": "deployment_name", "required": True, "secret": False, "in_": "config"},
    ],
    "hosted_vllm": [
        {"name": "api_key", "required": False, "secret": True, "in_": "credentials"},
        {"name": "endpoint", "required": True, "secret": False, "in_": "config"},
    ],
}


def get_field_definitions(provider: str) -> list[FieldDefinition]:
    """
    Get field definitions for a provider.

    Returns provider-specific fields if configured, otherwise DEFAULT_FIELDS.
    Resolves aliases (e.g. 'vllm' -> 'hosted_vllm') before lookup.
    """
    canonical = get_canonical_provider_type(provider)
    return PROVIDER_FIELD_DEFINITIONS.get(canonical, DEFAULT_FIELDS)


# --- Legacy helpers (kept for backward compatibility) ---

# Provider-specific required fields
# - All providers require at minimum: api_key
# - Azure requires: api_key, endpoint, api_version, deployment_name
# - hosted_vllm requires: api_key, endpoint (for self-hosted vLLM servers)
PROVIDER_REQUIRED_FIELDS: dict[str, Set[str]] = {
    "openai": {"api_key"},
    "anthropic": {"api_key"},
    "azure": {"api_key", "endpoint", "api_version", "deployment_name"},
    "hosted_vllm": {"api_key", "endpoint"},
    "mistral": {"api_key"},
    "ovhcloud": {"api_key"},
    "gemini": {"api_key"},
    "cohere": {"api_key"},
}


def get_required_fields(provider: str) -> Set[str]:
    """
    Get the set of required fields for a given provider.

    Args:
        provider: Provider name (case-insensitive)

    Returns:
        Set of required field names. Defaults to {"api_key"} for unknown providers.
    """
    return PROVIDER_REQUIRED_FIELDS.get(provider.lower(), {"api_key"})


def is_field_required(provider: str, field: str) -> bool:
    """
    Check if a specific field is required for a given provider.

    Args:
        provider: Provider name (case-insensitive)
        field: Field name (e.g., "api_key", "endpoint")

    Returns:
        True if the field is required for this provider
    """
    required = get_required_fields(provider)
    return field in required


def validate_provider_credentials(
    provider: str, request_data: Any, strict_mode: bool
) -> list[str]:
    """
    Validate credentials against provider-specific requirements.

    Args:
        provider: LLM provider name
        request_data: Credential request with fields (must have attributes matching required fields)
        strict_mode: Whether tenant_credentials_enabled (strict mode)

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []

    # Get required fields for this provider from centralized config
    required_fields = get_required_fields(provider)

    # Check each required field
    for field in required_fields:
        value = getattr(request_data, field, None)
        if not value or (isinstance(value, str) and not value.strip()):
            errors.append(f"Field '{field}' is required for provider '{provider}'")

    # Additional validation: api_key minimum length
    if request_data.api_key and len(request_data.api_key.strip()) < 8:
        errors.append("API key must be at least 8 characters long")

    return errors
