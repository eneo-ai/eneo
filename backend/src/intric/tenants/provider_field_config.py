"""
Centralized configuration for provider-specific credential field requirements.

This module defines which fields are required for each LLM provider's credentials.
Used by routers, validators, and domain models to ensure consistency.
"""

from typing import Any, Set

# Provider-specific required fields
# - All providers require at minimum: api_key
# - Azure requires: api_key, endpoint, api_version, deployment_name
# - vLLM requires: api_key, endpoint
PROVIDER_REQUIRED_FIELDS: dict[str, Set[str]] = {
    "openai": {"api_key"},
    "anthropic": {"api_key"},
    "azure": {"api_key", "endpoint", "api_version", "deployment_name"},
    "berget": {"api_key"},
    "gdm": {"api_key"},
    "mistral": {"api_key"},
    "ovhcloud": {"api_key"},
    "vllm": {"api_key", "endpoint"},
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
