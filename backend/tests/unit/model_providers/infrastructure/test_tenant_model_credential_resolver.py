"""The stored key reaches litellm exactly as the operator meant it: trimmed,
and absent rather than blank."""

from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from eneo.model_providers.infrastructure.tenant_model_credential_resolver import (
    TenantModelCredentialResolver,
)
from eneo.settings.encryption_service import EncryptionService

_ENCRYPTION = EncryptionService(Fernet.generate_key().decode())


def _resolver(stored_key: str) -> TenantModelCredentialResolver:
    return TenantModelCredentialResolver(
        provider_id=uuid4(),
        provider_type="openai",
        credentials={"api_key": _ENCRYPTION.encrypt(stored_key)},
        config={},
        encryption_service=_ENCRYPTION,
    )


def test_a_key_stored_with_a_trailing_newline_is_resolved_trimmed() -> None:
    assert _resolver("sk-abc\n").get_api_key() == "sk-abc"


def test_a_whitespace_only_key_is_no_key_when_optional() -> None:
    assert _resolver(" \n").get_api_key(required=False) is None


def test_a_whitespace_only_key_is_missing_when_required() -> None:
    with pytest.raises(ValueError, match="No API key found"):
        _resolver("  ").get_api_key()
