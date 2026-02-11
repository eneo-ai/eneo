"""Unit tests for federation config secret masking.

Verifies that get_federation_config_with_metadata decrypts the
client_secret before masking it, so the masked output reflects the
real secret — not the Fernet ciphertext stored in the database.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.tenants.tenant_repo import TenantRepository


def _make_repo(*, encryption_service=None):
    session = AsyncMock()
    return TenantRepository(session=session, encryption_service=encryption_service), session


def _mock_scalar_one(session, value):
    result = MagicMock()
    result.scalar_one.return_value = value
    session.execute.return_value = result


@pytest.mark.asyncio
async def test_masks_decrypted_secret_not_ciphertext():
    """Encrypted client_secret must be decrypted before masking."""
    encryption = MagicMock()
    encryption.is_active.return_value = True
    encryption.decrypt.return_value = "my-real-secret-value"

    repo, session = _make_repo(encryption_service=encryption)

    _mock_scalar_one(session, {
        "provider": "auth0",
        "client_id": "cid",
        "client_secret": "enc:fernet:v1:fake-ciphertext",
        "issuer": "https://example.com",
        "allowed_domains": ["example.com"],
        "encrypted_at": "2025-01-01T00:00:00+00:00",
    })

    result = await repo.get_federation_config_with_metadata(uuid4())

    encryption.decrypt.assert_called_once_with("enc:fernet:v1:fake-ciphertext")
    assert result["masked_secret"] == "...alue"
    assert result["encryption_status"] == "encrypted"


@pytest.mark.asyncio
async def test_masks_plaintext_secret_when_no_encryption():
    """Without encryption service, plaintext secret is masked directly."""
    repo, session = _make_repo(encryption_service=None)

    _mock_scalar_one(session, {
        "provider": "okta",
        "client_id": "cid",
        "client_secret": "plain-secret-abcd",
        "issuer": "https://example.com",
        "allowed_domains": [],
        "encrypted_at": None,
    })

    result = await repo.get_federation_config_with_metadata(uuid4())

    assert result["masked_secret"] == "...abcd"
    assert result["encryption_status"] == "plaintext"


@pytest.mark.asyncio
async def test_handles_decryption_failure_gracefully():
    """If decryption fails, masks the raw value and doesn't crash."""
    encryption = MagicMock()
    encryption.decrypt.side_effect = ValueError("bad token")

    repo, session = _make_repo(encryption_service=encryption)

    _mock_scalar_one(session, {
        "provider": "entra",
        "client_id": "cid",
        "client_secret": "enc:fernet:v1:corrupted-data",
        "issuer": "https://example.com",
        "allowed_domains": [],
        "encrypted_at": None,
    })

    result = await repo.get_federation_config_with_metadata(uuid4())

    # Should not crash — falls back to masking the raw value
    assert result["masked_secret"] is not None
    assert result["encryption_status"] == "encrypted"


@pytest.mark.asyncio
async def test_returns_none_when_no_config():
    """Returns None when tenant has no federation config."""
    repo, session = _make_repo()

    _mock_scalar_one(session, None)

    result = await repo.get_federation_config_with_metadata(uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_short_secret_masked_completely():
    """Secrets <= 4 chars are fully masked as '***'."""
    repo, session = _make_repo(encryption_service=None)

    _mock_scalar_one(session, {
        "provider": "test",
        "client_id": "cid",
        "client_secret": "ab",
        "issuer": None,
        "allowed_domains": [],
        "encrypted_at": None,
    })

    result = await repo.get_federation_config_with_metadata(uuid4())
    assert result["masked_secret"] == "***"
